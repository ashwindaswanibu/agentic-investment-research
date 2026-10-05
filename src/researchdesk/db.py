from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "research_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    hypothesis: Mapped[str] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    summary: Mapped[str] = mapped_column(Text, default="")
    tool_budget: Mapped[int] = mapped_column(Integer)
    tool_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class TaskRow(Base):
    __tablename__ = "research_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("research_cases.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("research_tasks.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    worker_id: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[float | None] = mapped_column(Float, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    started_at: Mapped[str | None] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))


class ArtifactRow(Base):
    __tablename__ = "research_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("research_cases.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("research_tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[object] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class ToolRow(Base):
    __tablename__ = "research_tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("research_tasks.id"), index=True)
    call_id: Mapped[str] = mapped_column(String(200))
    call_key: Mapped[str] = mapped_column(String(300), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="running")
    result: Mapped[object | None] = mapped_column(JSON, nullable=True)
    error: Mapped[object | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    finished_at: Mapped[str | None] = mapped_column(String(40))


class EventRow(Base):
    __tablename__ = "research_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("research_cases.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("research_tasks.id"))
    kind: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class AccountRow(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class LedgerRow(Base):
    __tablename__ = "paper_ledger"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    event: Mapped[dict] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))


class SystemRow(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


def make_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        if url not in {"sqlite://", "sqlite:///:memory:"}:
            path = url.split("///", 1)[1]
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")

    return engine
