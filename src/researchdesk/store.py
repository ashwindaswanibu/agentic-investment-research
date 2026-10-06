"""Short, committed transactions for research work and immutable evidence.

SQLite supports a local worker; PostgreSQL claims use row locks with SKIP LOCKED.
There is deliberately no database transaction held across a model or tool call.
"""

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from researchdesk.db import (
    AccountRow,
    ArtifactRow,
    Base,
    CaseRow,
    EventRow,
    LedgerRow,
    PaperControlRow,
    SystemRow,
    TaskRow,
    ToolRow,
    make_engine,
    utcnow,
)
from researchdesk.errors import DomainError

TERMINAL = {"completed", "failed", "blocked", "cancelled"}
ROLES = {"coordinator", "researcher", "coder", "reviewer"}
KINDS = {
    "evidence",
    "dataset",
    "options_chain",
    "options_expirations",
    "instrument_comparison",
    "code",
    "experiment",
    "strategy_assessment",
    "review",
    "note",
    "paper_intent",
    "clinical_dossier",
    "hypothesis",
    "evaluation_reference",
    "evaluation_report",
    "specialist_spec",
    "specialist_activation",
    "research_tool_spec",
    "research_tool_tests",
    "research_tool_qualification",
    "research_tool_result",
    "forecast",
    "forecast_resolution",
}
# Gold labels and their detailed error reports belong to the operator's evaluator.
# No model tool, retrieval query or generated program receives these artifacts.
PROTECTED_KINDS = {"evaluation_reference", "evaluation_report"}
WORKSPACES = [
    {
        "id": "general",
        "name": "Investment research",
        "description": "Investigate mechanisms, evidence, and competing explanations.",
    },
    {
        "id": "quantitative",
        "name": "Quantitative strategies",
        "description": "Develop and evaluate reproducible strategies with chronological data.",
    },
    {
        "id": "clinical",
        "name": "Clinical evidence",
        "description": "Investigate trial evidence, uncertainty, "
        "and implications for investment hypotheses.",
    },
]


def content_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def row_dict(row) -> dict:
    result = {p.key: getattr(row, p.key) for p in inspect(type(row)).column_attrs}
    if isinstance(row, ArtifactRow):
        result["metadata"] = result.pop("details")
    result.pop("request_hash", None)
    result.pop("idempotency_key", None)
    result.pop("call_key", None)
    return result


def require(session, model, identifier):
    row = session.get(model, identifier)
    if row is None:
        raise DomainError("NOT_FOUND", "The requested resource does not exist.", 404)
    return row


class Store:
    def __init__(self, database_url: str):
        self.engine = make_engine(database_url)
        Base.metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    @staticmethod
    def _case_lock(session, case_id, skip_locked=False):
        row = session.scalar(
            select(CaseRow)
            .where(CaseRow.id == case_id)
            .with_for_update(skip_locked=skip_locked)
            .execution_options(populate_existing=True)
        )
        if row is None and not skip_locked:
            raise DomainError("NOT_FOUND", "Research case does not exist.", 404)
        return row

    def _task_lock(self, session, task_id):
        # All writes involving both tables lock the case before its task. This
        # serializes cancellation/claim/commit and avoids reverse-order deadlocks.
        case_id = session.scalar(select(TaskRow.case_id).where(TaskRow.id == task_id))
        if case_id is None:
            raise DomainError("NOT_FOUND", "Task does not exist.", 404)
        self._case_lock(session, case_id)
        return session.scalar(
            select(TaskRow)
            .where(TaskRow.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    @contextmanager
    def transaction(self):
        with Session(self.engine) as session:
            try:
                if self.engine.dialect.name == "sqlite":
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    session.begin()
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @staticmethod
    def _check_lease(task, worker_id):
        if worker_id is not None and (
            task.worker_id != worker_id
            or (task.lease_until or 0) <= time.time()
            or task.cancel_requested
        ):
            raise DomainError("LEASE_LOST", "The worker no longer owns this task.", 409)

    @staticmethod
    def _event(session, case_id, kind, data, task_id=None):
        row = EventRow(case_id=case_id, task_id=task_id, kind=kind, data=data)
        session.add(row)
        session.flush()
        return row_dict(row)

    @staticmethod
    def _existing(session, model, key, digest):
        if not key:
            return None
        row = session.scalar(select(model).where(model.idempotency_key == key))
        if row and row.request_hash != digest:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "This request key was used for different input.", 409
            )
        return row

    def create_case(
        self, title, hypothesis, workspace_id="general", tool_budget=40, idempotency_key=None
    ):
        if (
            not title.strip()
            or len(title) > 200
            or not hypothesis.strip()
            or len(hypothesis) > 12000
        ):
            raise DomainError("INVALID_CASE", "Provide a title and a bounded research question.")
        if workspace_id not in {w["id"] for w in WORKSPACES} or not 1 <= tool_budget <= 200:
            raise DomainError("INVALID_CASE", "Unknown workspace or invalid tool budget.")
        data = dict(
            title=title.strip(),
            hypothesis=hypothesis.strip(),
            workspace_id=workspace_id,
            tool_budget=tool_budget,
        )
        digest = content_hash(data)
        try:
            with self.transaction() as s:
                row = self._existing(s, CaseRow, idempotency_key, digest)
                if row:
                    return row_dict(row)
                row = CaseRow(
                    id=str(uuid4()), **data, idempotency_key=idempotency_key, request_hash=digest
                )
                s.add(row)
                s.flush()
                self._event(s, row.id, "case.created", {"title": row.title})
                return row_dict(row)
        except IntegrityError:
            with Session(self.engine) as s:
                row = self._existing(s, CaseRow, idempotency_key, digest)
                if row:
                    return row_dict(row)
            raise

    def get_case(self, case_id):
        with Session(self.engine) as s:
            return row_dict(require(s, CaseRow, case_id))

    def list_cases(self):
        with Session(self.engine) as s:
            return [
                row_dict(r)
                for r in s.scalars(select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(200))
            ]

    def update_case(self, case_id, **fields):
        if set(fields) - {"status", "summary"}:
            raise DomainError("INVALID_UPDATE", "Unsupported case field.")
        if "status" in fields and fields["status"] not in {
            "draft",
            "queued",
            "running",
            "waiting",
            "completed",
            "failed",
            "cancelled",
        }:
            raise DomainError("INVALID_STATUS", "Unknown case status.")
        with self.transaction() as s:
            row = self._case_lock(s, case_id)
            if row.status == "cancelled" and fields.get("status", "cancelled") != "cancelled":
                return row_dict(row)
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = utcnow()
            self._event(s, case_id, "case.updated", fields)
            return row_dict(row)

    def create_task(
        self,
        case_id,
        role,
        instruction,
        parent_id=None,
        artifact_ids=None,
        idempotency_key=None,
        worker_id=None,
    ):
        if role not in ROLES or not instruction.strip() or len(instruction) > 24000:
            raise DomainError("INVALID_TASK", "Unknown role or invalid assignment.")
        data = dict(
            case_id=case_id,
            role=role,
            instruction=instruction,
            parent_id=parent_id,
            artifact_ids=artifact_ids or [],
        )
        digest = content_hash(data)
        try:
            with self.transaction() as s:
                row = self._existing(s, TaskRow, idempotency_key, digest)
                if row:
                    return row_dict(row)
                case = s.scalar(select(CaseRow).where(CaseRow.id == case_id).with_for_update())
                if case is None:
                    raise DomainError("NOT_FOUND", "Research case does not exist.", 404)
                if case.status == "cancelled":
                    raise DomainError("CANCELLED", "This research case was cancelled.", 409)
                if parent_id:
                    parent = require(s, TaskRow, parent_id)
                    self._check_lease(parent, worker_id)
                    if parent.case_id != case_id:
                        raise DomainError(
                            "INVALID_PARENT", "Parent belongs to another research case."
                        )
                elif s.scalar(
                    select(TaskRow.id)
                    .where(
                        TaskRow.case_id == case_id,
                        TaskRow.parent_id.is_(None),
                        TaskRow.status.not_in(TERMINAL),
                    )
                    .limit(1)
                ):
                    raise DomainError(
                        "CASE_ALREADY_RUNNING", "This case already has an active coordinator.", 409
                    )
                for aid in data["artifact_ids"]:
                    require(s, ArtifactRow, aid)
                count = s.scalar(
                    select(func.count()).select_from(TaskRow).where(TaskRow.case_id == case_id)
                )
                if count >= min(case.tool_budget + 1, 64):
                    raise DomainError(
                        "TASK_LIMIT", "The case delegation limit has been reached.", 409
                    )
                row = TaskRow(
                    id=str(uuid4()), **data, idempotency_key=idempotency_key, request_hash=digest
                )
                s.add(row)
                s.flush()
                case.status = "queued" if parent_id is None else "running"
                case.updated_at = utcnow()
                self._event(s, case_id, "task.queued", {"role": role}, row.id)
                return row_dict(row)
        except IntegrityError:
            with Session(self.engine) as s:
                row = self._existing(s, TaskRow, idempotency_key, digest)
                if row:
                    return row_dict(row)
            raise

    def get_task(self, task_id):
        with Session(self.engine) as s:
            return row_dict(require(s, TaskRow, task_id))

    def list_tasks(self, case_id=None, status=None):
        query = select(TaskRow).order_by(TaskRow.created_at)
        if case_id:
            query = query.where(TaskRow.case_id == case_id)
        if status:
            query = query.where(TaskRow.status == status)
        with Session(self.engine) as s:
            return [row_dict(r) for r in s.scalars(query.limit(500))]

    def resume_task(self, task_id, waiting_for, feedback):
        """Wake a parent once, even when several workers observe completion."""
        with self.transaction() as s:
            row = self._task_lock(s, task_id)
            if row is None or row.status != "waiting" or row.cancel_requested:
                return False
            checkpoint = dict(row.checkpoint or {})
            if checkpoint.get("waiting_for") != waiting_for:
                return False
            children = [require(s, TaskRow, child_id) for child_id in waiting_for]
            if not children or any(
                c.parent_id != task_id or c.status not in TERMINAL for c in children
            ):
                return False
            wake_id = ",".join(waiting_for)
            messages = list(row.messages or [])
            if not any(m.get("delegation_wake") == wake_id for m in messages):
                messages.append(
                    {"role": "user", "content": json.dumps(feedback), "delegation_wake": wake_id}
                )
            row.messages = messages
            checkpoint.pop("waiting_for", None)
            row.checkpoint = checkpoint
            row.status, row.worker_id, row.lease_until = "queued", None, None
            self._event(s, row.case_id, "task.resumed", {"child_ids": waiting_for}, task_id)
            return True

    def claim_task(self, worker_id, lease_seconds=120, task_id=None):
        now = time.time()
        available = or_(
            TaskRow.status == "queued", and_(TaskRow.status == "running", TaskRow.lease_until < now)
        )
        with self.transaction() as s:
            query = (
                select(TaskRow)
                .where(available, TaskRow.cancel_requested.is_(False))
                .order_by(TaskRow.created_at)
                .limit(1)
            )
            if task_id:
                query = query.where(TaskRow.id == task_id)
            row = s.scalar(query)
            if row is None:
                return None
            case = self._case_lock(s, row.case_id, skip_locked=True)
            if case is None:
                return None
            s.refresh(row)
            if (
                row.cancel_requested
                or row.status not in {"queued", "running"}
                or (row.status == "running" and (row.lease_until or 0) >= now)
            ):
                return None
            if row.attempt >= 5:
                row.status = "failed"
                row.error = {
                    "code": "RECOVERY_EXHAUSTED",
                    "message": "Worker recovery attempts exhausted.",
                }
                row.finished_at = utcnow()
                self._event(s, row.case_id, "task.failed", row.error, row.id)
                return None
            claimed = s.execute(
                update(TaskRow)
                .where(TaskRow.id == row.id, available)
                .values(
                    status="running",
                    worker_id=worker_id,
                    lease_until=now + lease_seconds,
                    attempt=TaskRow.attempt + 1,
                    started_at=row.started_at or utcnow(),
                )
                .returning(TaskRow.id),
                execution_options={"synchronize_session": False},
            ).scalar_one_or_none()
            if claimed is None:
                return None
            s.expire(row)
            case = require(s, CaseRow, row.case_id)
            case.status = "running"
            case.updated_at = utcnow()
            self._event(s, row.case_id, "task.running", {"attempt": row.attempt}, row.id)
            return row_dict(row)

    def renew_lease(self, task_id, worker_id, lease_seconds=120):
        now = time.time()
        with self.transaction() as s:
            result = s.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == task_id,
                    TaskRow.worker_id == worker_id,
                    TaskRow.status == "running",
                    TaskRow.lease_until > now,
                    TaskRow.cancel_requested.is_(False),
                )
                .values(lease_until=now + lease_seconds)
            )
            return result.rowcount == 1

    def update_task(self, task_id, worker_id=None, **fields):
        allowed = {"status", "checkpoint", "result", "error", "summary", "cancel_requested"}
        if set(fields) - allowed:
            raise DomainError("INVALID_UPDATE", "Unsupported task field.")
        if "status" in fields and fields["status"] not in TERMINAL | {
            "queued",
            "running",
            "waiting",
        }:
            raise DomainError("INVALID_STATUS", "Unknown task status.")
        with self.transaction() as s:
            row = self._task_lock(s, task_id)
            if row is None:
                raise DomainError("NOT_FOUND", "Task does not exist.", 404)
            if worker_id is not None and (
                row.worker_id != worker_id or (row.lease_until or 0) <= time.time()
            ):
                raise DomainError("LEASE_LOST", "The worker no longer owns this task.", 409)
            if row.status in TERMINAL and fields.get("status", row.status) != row.status:
                raise DomainError(
                    "TERMINAL_TASK",
                    "A completed task cannot be rewritten; create a new revision.",
                    409,
                )
            if row.cancel_requested:
                fields["status"] = "cancelled"
            for key, value in fields.items():
                setattr(row, key, value)
            if row.status in TERMINAL:
                row.finished_at = utcnow()
            if row.status != "running":
                row.lease_until = None
                row.worker_id = None
            if row.parent_id is None:
                case = require(s, CaseRow, row.case_id)
                if case.status != "cancelled":
                    case.status = "failed" if row.status == "blocked" else row.status
                    case.summary = row.summary
                    case.updated_at = utcnow()
            self._event(s, row.case_id, "task.updated", {"status": row.status}, row.id)
            return row_dict(row)

    def is_cancelled(self, task_id):
        task = self.get_task(task_id)
        return task["cancel_requested"] or task["status"] == "cancelled"

    def cancel_case(self, case_id):
        with self.transaction() as s:
            case = self._case_lock(s, case_id)
            case.status, case.updated_at = "cancelled", utcnow()
            for row in s.scalars(select(TaskRow).where(TaskRow.case_id == case_id)):
                if row.status not in TERMINAL:
                    row.cancel_requested = True
                    row.status, row.finished_at = "cancelled", utcnow()
                    row.worker_id, row.lease_until = None, None
                    for call in s.scalars(
                        select(ToolRow).where(
                            ToolRow.task_id == row.id, ToolRow.status == "running"
                        )
                    ):
                        call.status, call.finished_at = "blocked", utcnow()
                        call.error = {
                            "code": "CANCELLED",
                            "message": "The research case was cancelled.",
                        }
                        call.result = {"ok": False, "error": call.error}
            self._event(s, case_id, "case.cancelled", {})
            return row_dict(case)

    def append_event(self, case_id, kind, data, task_id=None):
        with self.transaction() as s:
            return self._event(s, case_id, kind, data, task_id)

    def list_events(self, case_id=None, after=0, limit=200):
        query = select(EventRow).where(EventRow.seq > after).order_by(EventRow.seq)
        if case_id:
            query = query.where(EventRow.case_id == case_id)
        with Session(self.engine) as s:
            return [row_dict(r) for r in s.scalars(query.limit(min(limit, 1000)))]

    def consume_budget(self, case_id, amount=1):
        if amount < 1:
            raise DomainError("INVALID_BUDGET", "Budget consumption must be positive.")
        with self.transaction() as s:
            result = s.execute(
                update(CaseRow)
                .where(
                    CaseRow.id == case_id, CaseRow.tool_calls_used + amount <= CaseRow.tool_budget
                )
                .values(tool_calls_used=CaseRow.tool_calls_used + amount)
            )
            return result.rowcount == 1

    def put_artifact(
        self,
        case_id,
        task_id,
        kind,
        title,
        content,
        metadata=None,
        idempotency_key=None,
        worker_id=None,
        require_active_case=False,
    ):
        if kind not in KINDS or not title.strip() or len(title) > 200:
            raise DomainError("INVALID_ARTIFACT", "Unknown artifact type or invalid title.")
        encoded = json.dumps(content, allow_nan=False)
        if len(encoded.encode()) > 2_000_000:
            raise DomainError("ARTIFACT_TOO_LARGE", "Artifact exceeds the two-megabyte limit.", 413)
        digest = content_hash(
            dict(
                case_id=case_id,
                task_id=task_id,
                kind=kind,
                title=title,
                content=content,
                metadata=metadata or {},
            )
        )
        try:
            with self.transaction() as s:
                existing = self._existing(s, ArtifactRow, idempotency_key, digest)
                if existing:
                    return row_dict(existing)
                case = self._case_lock(s, case_id)
                if require_active_case and case.status == "cancelled":
                    raise DomainError("CANCELLED", "This investigation has been cancelled.", 409)
                if task_id:
                    self._check_lease(self._task_lock(s, task_id), worker_id)
                if task_id and require(s, TaskRow, task_id).case_id != case_id:
                    raise DomainError("INVALID_TASK", "Artifact producer belongs to another case.")
                row = ArtifactRow(
                    id=str(uuid4()),
                    case_id=case_id,
                    task_id=task_id,
                    kind=kind,
                    title=title,
                    content=content,
                    sha256=content_hash(content),
                    details=metadata or {},
                    idempotency_key=idempotency_key,
                    request_hash=digest,
                )
                s.add(row)
                s.flush()
                self._event(
                    s,
                    case_id,
                    "artifact.created",
                    {"artifact_id": row.id, "kind": kind, "title": title, "sha256": row.sha256},
                    task_id,
                )
                return row_dict(row)
        except IntegrityError:
            with Session(self.engine) as s:
                row = self._existing(s, ArtifactRow, idempotency_key, digest)
                if row:
                    return row_dict(row)
            raise

    def get_artifact(self, artifact_id):
        with Session(self.engine) as s:
            row = require(s, ArtifactRow, artifact_id)
            if row.sha256 != content_hash(row.content):
                raise DomainError(
                    "ARTIFACT_CORRUPT", "Artifact content failed integrity verification.", 409
                )
            return row_dict(row)

    def put_forecast_artifact(
        self,
        case_id,
        kind,
        request,
        build,
        validate_commit,
        *,
        idempotency_key,
        task_id=None,
        worker_id=None,
    ):
        """Append a timed forecast record under the same case/lease write fence.

        Only immutable request inputs enter the retry digest. The builder runs
        after the case lock and retry lookup, so timestamps and latest-resolution
        checks cannot make an identical retry disagree with its committed result.
        The final timing guard runs after flush, immediately before commit.
        """
        if kind not in {"forecast", "forecast_resolution"}:
            raise DomainError("INVALID_ARTIFACT", "Expected a forecast lifecycle artifact.")
        digest = content_hash(dict(case_id=case_id, task_id=task_id, kind=kind, request=request))
        with self.transaction() as s:
            case = self._case_lock(s, case_id)
            if case.status == "cancelled":
                raise DomainError("CANCELLED", "This investigation has been cancelled.", 409)
            if task_id:
                task = self._task_lock(s, task_id)
                self._check_lease(task, worker_id)
                if task.case_id != case_id:
                    raise DomainError("INVALID_TASK", "Artifact producer belongs to another case.")
            existing = self._existing(s, ArtifactRow, idempotency_key, digest)
            if existing:
                if content_hash(existing.content) != existing.sha256:
                    raise DomainError("ARTIFACT_CORRUPT", "Saved forecast failed integrity.", 409)
                return row_dict(existing)
            title, content, metadata = build(s, datetime.now(UTC))
            if not title.strip() or len(title) > 200:
                raise DomainError("INVALID_ARTIFACT", "Provide a bounded artifact title.")
            if len(json.dumps(content, allow_nan=False).encode()) > 2_000_000:
                raise DomainError("ARTIFACT_TOO_LARGE", "Artifact exceeds two megabytes.", 413)
            row = ArtifactRow(
                id=str(uuid4()),
                case_id=case_id,
                task_id=task_id,
                kind=kind,
                title=title,
                content=content,
                sha256=content_hash(content),
                details=metadata,
                idempotency_key=idempotency_key,
                request_hash=digest,
            )
            s.add(row)
            s.flush()
            self._event(
                s,
                case_id,
                "artifact.created",
                {
                    "artifact_id": row.id,
                    "kind": kind,
                    "title": title,
                    "sha256": row.sha256,
                },
                task_id,
            )
            if task_id:
                self._check_lease(task, worker_id)
            validate_commit(datetime.now(UTC))
            return row_dict(row)

    def list_forecast_artifacts(self, case_id):
        """Return complete history; the ordinary library's 500-item cap does not apply."""
        with Session(self.engine) as s:
            require(s, CaseRow, case_id)
            rows = s.scalars(
                select(ArtifactRow)
                .where(
                    ArtifactRow.case_id == case_id,
                    ArtifactRow.kind.in_({"forecast", "forecast_resolution"}),
                )
                .order_by(ArtifactRow.created_at, ArtifactRow.id)
            )
            result = []
            for row in rows:
                if content_hash(row.content) != row.sha256:
                    raise DomainError("ARTIFACT_CORRUPT", "Saved forecast failed integrity.", 409)
                result.append(row_dict(row))
            return result

    def recover_tool_artifact(self, task_id, call_id, name, arguments, worker_id):
        """Recover the committed effect of a tool whose completion record was interrupted.

        Match the original invocation before returning the artifact. Do not refetch
        a changing source or rerun generated code after its output already committed.
        """
        key = f"{task_id}:{call_id}"
        with self.transaction() as s:
            task = self._task_lock(s, task_id)
            self._check_lease(task, worker_id)
            call = s.scalar(select(ToolRow).where(ToolRow.call_key == key))
            if call is None:
                return None
            if call.name != name or content_hash(call.arguments) != content_hash(arguments):
                raise DomainError("CALL_CONFLICT", "The original tool invocation must match.", 409)
            if call.status != "running":
                return None
            artifact = s.scalar(select(ArtifactRow).where(ArtifactRow.idempotency_key == key))
            if artifact is None:
                return None
            if artifact.task_id != task_id or artifact.case_id != task.case_id:
                raise DomainError(
                    "ARTIFACT_TASK", "The committed output has invalid ownership.", 409
                )
            if artifact.kind in PROTECTED_KINDS:
                raise DomainError("PROTECTED_EVALUATION", "Evaluation labels are protected.", 403)
            if artifact.sha256 != content_hash(artifact.content):
                raise DomainError(
                    "ARTIFACT_CORRUPT", "Committed output failed integrity checks.", 409
                )
            return row_dict(artifact)

    def list_artifacts(self, case_id=None, kind=None):
        query = select(ArtifactRow).order_by(ArtifactRow.created_at.desc())
        if case_id:
            query = query.where(ArtifactRow.case_id == case_id)
        if kind:
            query = query.where(ArtifactRow.kind == kind)
        with Session(self.engine) as s:
            return [row_dict(r) for r in s.scalars(query.limit(500))]

    def begin_tool_call(self, task_id, call_id, name, arguments, worker_id=None):
        key = f"{task_id}:{call_id}"
        try:
            with self.transaction() as s:
                self._check_lease(self._task_lock(s, task_id), worker_id)
                old = s.scalar(select(ToolRow).where(ToolRow.call_key == key))
                if old:
                    if old.name != name or old.arguments != arguments:
                        raise DomainError(
                            "CALL_CONFLICT", "Tool call ID was reused for different arguments.", 409
                        )
                    return row_dict(old)
                task = require(s, TaskRow, task_id)
                if task.cancel_requested:
                    raise DomainError("CANCELLED", "Task was cancelled.", 409)
                row = ToolRow(
                    id=str(uuid4()),
                    task_id=task_id,
                    call_id=call_id,
                    call_key=key,
                    name=name,
                    arguments=arguments,
                )
                s.add(row)
                s.flush()
                consumed = s.execute(
                    update(CaseRow)
                    .where(
                        CaseRow.id == task.case_id, CaseRow.tool_calls_used < CaseRow.tool_budget
                    )
                    .values(tool_calls_used=CaseRow.tool_calls_used + 1)
                ).rowcount
                if not consumed:
                    row.status = "blocked"
                    row.error = {
                        "code": "BUDGET_EXHAUSTED",
                        "message": "The shared research budget is exhausted.",
                    }
                    row.result = {"ok": False, "error": row.error}
                    row.finished_at, row.duration_ms = utcnow(), 0
                self._event(
                    s,
                    task.case_id,
                    "tool." + row.status,
                    {"tool_id": row.id, "name": name},
                    task_id,
                )
                return row_dict(row)
        except IntegrityError:
            with Session(self.engine) as s:
                old = s.scalar(select(ToolRow).where(ToolRow.call_key == key))
                if old and old.name == name and old.arguments == arguments:
                    return row_dict(old)
            raise

    def finish_tool_call(self, tool_id, status, result=None, error=None, worker_id=None):
        if status not in {"completed", "failed", "blocked"}:
            raise DomainError("INVALID_STATUS", "Tool result must be terminal.")
        with self.transaction() as s:
            row = require(s, ToolRow, tool_id)
            self._check_lease(self._task_lock(s, row.task_id), worker_id)
            s.refresh(row)
            if row.status != "running":
                return row_dict(row)
            row.status, row.result, row.error = status, result, error
            row.finished_at = utcnow()
            row.duration_ms = max(
                0,
                int(
                    (datetime.now(UTC) - datetime.fromisoformat(row.started_at)).total_seconds()
                    * 1000
                ),
            )
            task = require(s, TaskRow, row.task_id)
            self._event(
                s,
                task.case_id,
                "tool." + status,
                {"tool_id": row.id, "name": row.name},
                row.task_id,
            )
            return row_dict(row)

    def list_tool_calls(self, task_id=None, case_id=None):
        query = select(ToolRow).order_by(ToolRow.started_at)
        if task_id:
            query = query.where(ToolRow.task_id == task_id)
        if case_id:
            query = query.join(TaskRow).where(TaskRow.case_id == case_id)
        with Session(self.engine) as s:
            return [row_dict(r) for r in s.scalars(query.limit(1000))]

    def save_messages(self, task_id, messages, worker_id=None):
        with self.transaction() as s:
            task = self._task_lock(s, task_id)
            self._check_lease(task, worker_id)
            task.messages = messages

    def get_messages(self, task_id):
        with Session(self.engine) as s:
            return require(s, TaskRow, task_id).messages

    def set_system(self, key, value):
        with self.transaction() as s:
            row = s.get(SystemRow, key)
            if row:
                row.value = value
            else:
                s.add(SystemRow(key=key, value=value))

    def get_system(self, key):
        with Session(self.engine) as s:
            row = s.get(SystemRow, key)
            return row.value if row else None

    def ledger_events(self, account_id="paper-main"):
        with Session(self.engine) as s:
            return [
                r.event
                for r in s.scalars(
                    select(LedgerRow)
                    .where(LedgerRow.account_id == account_id)
                    .order_by(LedgerRow.seq)
                )
            ]

    def ledger_transaction(
        self,
        idempotency_key,
        make_events,
        account_id="paper-main",
        request=None,
        case_id=None,
    ):
        """Serialize admission+event commit; the callback is deterministic, no I/O.

        A no-op UPDATE acquires a write lock before replay even on SQLite. This
        prevents two reservations from both observing the same available cash.
        """
        with self.transaction() as s:
            if case_id and self._case_lock(s, case_id).status == "cancelled":
                raise DomainError("CANCELLED", "The originating research case was cancelled.", 409)
            if (request or {}).get("action") in {"reserve", "fill"}:
                control = s.scalar(
                    select(PaperControlRow)
                    .where(PaperControlRow.id == account_id)
                    .with_for_update()
                )
                if control and control.version > 0:
                    raise DomainError(
                        "MANAGED_ACCOUNT",
                        "This account is controlled by the paper operations worker.",
                        409,
                    )
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
            s.execute(insert(AccountRow).values(id=account_id, version=0).on_conflict_do_nothing())
            s.execute(
                update(AccountRow)
                .where(AccountRow.id == account_id)
                .values(version=AccountRow.version + 1)
            )
            old = s.scalar(select(LedgerRow).where(LedgerRow.idempotency_key == idempotency_key))
            if old:
                if old.account_id != account_id or old.request_hash != content_hash(request):
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT",
                        "This request key was used for a different paper action.",
                        409,
                    )
                return [old.event]
            events = [
                r.event
                for r in s.scalars(
                    select(LedgerRow)
                    .where(LedgerRow.account_id == account_id)
                    .order_by(LedgerRow.seq)
                )
            ]
            new_events = make_events(events)
            from researchdesk.paper import replay

            replay([*events, *new_events])
            for event_data in new_events:
                s.add(
                    LedgerRow(
                        account_id=account_id,
                        idempotency_key=event_data["idempotency_key"],
                        event=event_data,
                        request_hash=content_hash(request),
                    )
                )
            self._event(
                s, None, "paper.updated", {"account_id": account_id, "event_count": len(new_events)}
            )
            return new_events
