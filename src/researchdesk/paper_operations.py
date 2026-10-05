"""Bounded, leased paper monitoring. Network reads precede short atomic commits.

No brokerage order endpoint is used. Mandates are operator-owned immutable records.
The worker may consume existing reviewed equity intents; it does not invent trades.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from researchdesk.data.quotes import AlpacaQuoteProvider
from researchdesk.db import (
    AccountRow,
    ArtifactRow,
    LedgerRow,
    MarketSessionRow,
    PaperControlRow,
    PaperMandateRow,
    PaperObservationRow,
    SystemRow,
)
from researchdesk.errors import DomainError
from researchdesk.paper import (
    OrderIntent,
    PaperError,
    PaperEvent,
    PaperPolicy,
    fill_order,
    mark_portfolio,
    replay,
    reserve_order,
)
from researchdesk.paper.performance import MarketSession, ValuationObservation, build_performance
from researchdesk.quant.models import StrictModel
from researchdesk.store import content_hash, row_dict

ACCOUNT = "paper-main"
NY = ZoneInfo("America/New_York")
LEASE_SECONDS = 120


class ExplicitPolicy(StrictModel):
    max_symbol_weight: Decimal = Field(gt=0, le=1)
    max_order_notional: Decimal = Field(gt=0)
    max_quote_age_seconds: int = Field(ge=1, le=60, strict=True)
    fee_bps: Decimal = Field(ge=0, le=1000)


class MandateInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_symbols: list[str] = Field(min_length=1, max_length=30)
    policy: ExplicitPolicy
    max_open_orders: int = Field(ge=1, le=20, strict=True)
    order_ttl_seconds: int = Field(ge=60, le=86400, strict=True)
    max_decision_age_seconds: int = Field(ge=60, le=86400, strict=True)
    poll_interval_seconds: int = Field(ge=5, le=300, strict=True)
    max_drawdown_amount: Decimal = Field(gt=0)
    expires_at: datetime

    @field_validator("allowed_symbols")
    @classmethod
    def symbols(cls, value):
        import re

        if len(value) != len(set(value)) or any(
            not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in value
        ):
            raise ValueError("Supply unique uppercase instrument symbols.")
        return sorted(value)

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Expiry must include a timezone.")
        return value.astimezone(UTC)


class ControlInput(StrictModel):
    mandate_id: str | None
    mode: Literal["active", "exit_only", "halted"]
    expected_version: int = Field(ge=0, strict=True)


def quote_provider(settings):
    return AlpacaQuoteProvider(
        settings.alpaca_api_key, settings.alpaca_secret_key, feed=settings.alpaca_feed
    )


class PaperOperations:
    def __init__(self, store, research, provider):
        self.store, self.research, self.provider = store, research, provider
        with store.transaction() as session:
            self._insert(
                session,
                PaperControlRow,
                {
                    "id": ACCOUNT,
                    "version": 0,
                    "mode": "halted",
                    "fence": 0,
                    "drawdown_tripped": False,
                },
            )

    def _insert(self, session, model, values):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = pg_insert if self.store.engine.dialect.name == "postgresql" else sqlite_insert
        session.execute(insert(model).values(**values).on_conflict_do_nothing())

    @staticmethod
    def _control(session):
        return session.scalar(
            select(PaperControlRow).where(PaperControlRow.id == ACCOUNT).with_for_update()
        )

    def _account(self, session):
        self._insert(session, AccountRow, {"id": ACCOUNT, "version": 0})
        return session.scalar(select(AccountRow).where(AccountRow.id == ACCOUNT).with_for_update())

    @staticmethod
    def _events(session):
        return [
            r.event
            for r in session.scalars(
                select(LedgerRow).where(LedgerRow.account_id == ACCOUNT).order_by(LedgerRow.seq)
            )
        ]

    @staticmethod
    def _mandate(row):
        if not row or content_hash(row.payload) != row.sha256:
            raise DomainError(
                "MANDATE_INVALID", "Mandate is missing or failed its integrity check.", 409
            )
        return MandateInput.model_validate(row.payload)

    def create_mandate(self, body: MandateInput, key):
        payload = body.model_dump(mode="json")
        digest = content_hash(payload)
        with self.store.transaction() as session:
            # Serialize idempotency across concurrent operator requests.
            self._control(session)
            old = session.scalar(
                select(PaperMandateRow).where(PaperMandateRow.idempotency_key == key)
            )
            if old:
                if old.sha256 != digest:
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT", "Mandate key was reused with different fields.", 409
                    )
                return row_dict(old)
            if body.expires_at <= datetime.now(UTC):
                raise DomainError(
                    "MANDATE_EXPIRED", "A new mandate must expire in the future.", 409
                )
            row = PaperMandateRow(
                id=str(uuid4()), payload=payload, sha256=digest, idempotency_key=key
            )
            session.add(row)
            session.flush()
            return row_dict(row)

    @staticmethod
    def _append(session, account, events, new_events):
        if not new_events:
            return
        replay([*events, *new_events])
        for event in new_events:
            session.add(
                LedgerRow(
                    account_id=ACCOUNT,
                    idempotency_key=event["idempotency_key"],
                    event=event,
                    request_hash=content_hash({"operations_event": event}),
                )
            )
        account.version += 1

    @staticmethod
    def _cancel_events(events, predicate, reason, at):
        state = replay(events)
        return [
            PaperEvent(
                idempotency_key="ops-cancel:" + str(uuid4()),
                kind="order_cancelled",
                occurred_at=at,
                payload={"order_id": order_id, "reason": reason},
            ).model_dump(mode="json")
            for order_id, order in state.orders.items()
            if order.status == "open" and predicate(order)
        ]

    def set_control(self, body: ControlInput):
        with self.store.transaction() as session:
            control = self._control(session)
            if control.version != body.expected_version:
                raise DomainError(
                    "CONTROL_CONFLICT",
                    "Paper controls changed. Refresh before choosing an action.",
                    409,
                )
            row = session.get(PaperMandateRow, body.mandate_id) if body.mandate_id else None
            mandate = self._mandate(row) if row else None
            if body.mandate_id and row is None:
                raise DomainError("MANDATE_INVALID", "Select an existing saved mandate.", 409)
            now = datetime.now(UTC)
            if body.mode != "halted" and (mandate is None or mandate.expires_at <= now):
                raise DomainError(
                    "MANDATE_REQUIRED", "Activation requires a saved, unexpired mandate.", 409
                )
            if body.mode == "active" and row is not None and row.drawdown_tripped:
                raise DomainError(
                    "DRAWDOWN_LATCHED",
                    "Drawdown stop latched. Review and save a new mandate to resume entries.",
                    409,
                )
            account = self._account(session)
            events = self._events(session)
            if body.mode != "halted" and not events:
                raise DomainError(
                    "ACCOUNT_REQUIRED", "Open the paper account before activating operations.", 409
                )
            changed_mandate = body.mandate_id != control.mandate_id
            cancels = self._cancel_events(
                events,
                lambda order: (
                    changed_mandate
                    or body.mode == "halted"
                    or (body.mode == "exit_only" and order.intent.side == "buy")
                ),
                "Operator changed paper controls; no positions were liquidated.",
                now,
            )
            self._append(session, account, events, cancels)
            control.version += 1
            control.fence += 1
            control.mode, control.mandate_id = body.mode, body.mandate_id
            control.worker_id, control.lease_until = None, None
            if changed_mandate:
                control.peak_equity = row.peak_equity if row else None
                control.drawdown_tripped = row.drawdown_tripped if row else False
            self.store._event(
                session,
                None,
                "paper.control_changed",
                {
                    "version": control.version,
                    "mode": control.mode,
                    "mandate_id": control.mandate_id,
                    "cancelled_orders": len(cancels),
                },
            )
            return {
                "version": control.version,
                "mode": control.mode,
                "mandate_id": control.mandate_id,
            }

    def claim(self, worker_id):
        now = datetime.now(UTC)
        with self.store.transaction() as session:
            control = self._control(session)
            if control.lease_until and control.lease_until > now.timestamp():
                return None
            control.worker_id, control.lease_until = worker_id, now.timestamp() + LEASE_SECONDS
            control.fence += 1
            control.last_seen_at = now.isoformat()
            return {
                "worker_id": worker_id,
                "fence": control.fence,
                "version": control.version,
                "mandate_id": control.mandate_id,
            }

    def _fenced(self, session, token):
        control = self._control(session)
        if (
            any(getattr(control, key) != token[key] for key in ("worker_id", "fence", "version"))
            or not control.lease_until
            or control.lease_until <= datetime.now(UTC).timestamp()
        ):
            raise DomainError(
                "PAPER_LEASE_LOST",
                "Paper controls or worker ownership changed; this tick was discarded.",
                409,
            )
        return control

    def _candidates(self, mandate):
        if not mandate:
            return [], []
        candidates, rejected = [], []
        now = datetime.now(UTC)
        for artifact in reversed(self.store.list_artifacts(kind="paper_intent")):
            if (
                now - datetime.fromisoformat(artifact["created_at"])
            ).total_seconds() > mandate.max_decision_age_seconds:
                continue
            try:
                artifact = self.research.artifact(artifact["id"], kind="paper_intent")
                content = artifact["content"]
                self.research.validate_decision(
                    content["artifact_id"], content["review_id"], case_id=artifact["case_id"]
                )
                order = OrderIntent(
                    order_id=artifact["id"],
                    decision_id=artifact["id"],
                    **{k: content[k] for k in ("symbol", "side", "quantity", "limit_price")},
                )
                if order.symbol in mandate.allowed_symbols:
                    candidates.append((artifact, order))
            except (DomainError, ValueError, KeyError):
                rejected.append(
                    {"action": "rejected", "order_id": artifact["id"], "code": "DECISION_INVALID"}
                )
        return candidates, rejected

    def tick(self, worker_id):
        token = self.claim(worker_id)
        if token is None:
            return {"status": "leased_elsewhere"}
        quotes, calendar, clock, failure, calendar_range = {}, [], None, None, None
        with Session(self.store.engine) as session:
            row = session.get(PaperMandateRow, token["mandate_id"]) if token["mandate_id"] else None
            mandate = self._mandate(row) if row else None
        candidates, actions = self._candidates(mandate)
        state = replay(self.store.ledger_events())
        symbols = sorted(
            set(mandate.allowed_symbols if mandate else [])
            | set(state.positions)
            | {o.intent.symbol for o in state.orders.values() if o.status == "open"}
        )
        try:
            if not self.provider.health()["configured"]:
                raise DomainError(
                    "FEED_UNCONFIGURED",
                    "Configure Alpaca read-only market data credentials on the worker.",
                    409,
                )
            if len(symbols) > 120:
                raise DomainError(
                    "MONITOR_UNIVERSE_LIMIT",
                    "The monitored symbol count exceeds this worker's 120-symbol limit.",
                    409,
                )
            clock = self.provider.clock()
            today = datetime.now(UTC).astimezone(NY).date()
            calendar = self.provider.calendar(today - timedelta(days=16), today)
            calendar_range = (today - timedelta(days=16), today)
            for start in range(0, len(symbols), 30):
                quotes.update(self.provider.quotes(symbols[start : start + 30]).quotes)
            age = (datetime.now(UTC) - clock.timestamp).total_seconds()
            if not 0 <= age <= 60:
                raise DomainError(
                    "MARKET_CLOCK_STALE", "Market clock is stale or ahead of the local clock.", 409
                )
        except DomainError as exc:
            failure = exc.as_dict()
        except Exception:
            failure = {
                "code": "MARKET_DATA_FAILED",
                "message": "Market data could not be verified; no orders were executed.",
            }
        return self._commit_tick(
            token, mandate, candidates, actions, quotes, calendar, clock, failure, calendar_range
        )

    def _commit_tick(
        self,
        token,
        mandate,
        candidates,
        actions,
        quotes,
        calendar,
        clock,
        failure,
        calendar_range=None,
    ):
        with self.store.transaction() as session:
            # Global order: research cases -> controls -> account. No I/O under locks.
            cases = {a["case_id"] for a, _ in candidates}
            # Open orders retain their originating case for cancellation checks.
            prior = replay(self._events(session))
            open_cases = {}
            for order_id, order in prior.orders.items():
                if order.status == "open":
                    artifact = session.get(ArtifactRow, order.intent.decision_id)
                    open_cases[order_id] = artifact.case_id if artifact else None
            cases.update(case_id for case_id in open_cases.values() if case_id)
            cancelled = {
                case_id
                for case_id in sorted(cases)
                if self.store._case_lock(session, case_id).status == "cancelled"
            }
            control = self._fenced(session, token)
            account = self._account(session)
            events = self._events(session)
            now = datetime.now(UTC)
            policy = (
                PaperPolicy.model_validate(mandate.policy.model_dump())
                if mandate
                else PaperPolicy()
            )
            new_events = []

            def append(event):
                raw = event.model_dump(mode="json") if isinstance(event, PaperEvent) else event
                result = replay([*events, *new_events, raw])
                new_events.append(raw)
                return result

            state = replay(events)
            expired = mandate is not None and mandate.expires_at <= now
            if expired and control.mode != "halted":
                control.mode = "halted"
                control.version += 1
                actions.append({"action": "halted", "code": "MANDATE_EXPIRED"})
            if calendar_range:
                known = list(
                    session.scalars(
                        select(MarketSessionRow).where(
                            MarketSessionRow.session >= str(calendar_range[0]),
                            MarketSessionRow.session <= str(calendar_range[1]),
                        )
                    )
                )
                received = {
                    str(day.session): MarketSession(
                        session=day.session, open_at=day.open, close_at=day.close
                    ).model_dump(mode="json")
                    for day in calendar
                }
                if any(received.get(day.session) != day.payload for day in known):
                    failure = {
                        "code": "CALENDAR_CHANGED",
                        "message": "Retained session changed. Review the source calendar.",
                    }
                    calendar, calendar_range = [], None
            current_session = next((s for s in calendar if s.open <= now < s.close), None)
            if failure is None and clock and clock.is_open and current_session is None:
                failure = {
                    "code": "MARKET_SESSION_MISMATCH",
                    "message": "Market clock and official calendar disagree; execution is blocked.",
                }
            market_open = (
                failure is None
                and clock is not None
                and clock.is_open
                and current_session is not None
            )

            def check_drawdown(state):
                if failure is not None:
                    return
                try:
                    equity = (
                        Decimal(mark_portfolio(state, quotes, now, policy)["equity"])
                        if state.account_id
                        else None
                    )
                except PaperError:
                    equity = None
                if equity is not None and mandate:
                    peak = max(
                        Decimal(control.peak_equity) if control.peak_equity else equity, equity
                    )
                    control.peak_equity = str(peak)
                    mandate_row = session.get(PaperMandateRow, control.mandate_id)
                    mandate_row.peak_equity = str(peak)
                    if peak - equity >= mandate.max_drawdown_amount:
                        control.drawdown_tripped = True
                        mandate_row.drawdown_tripped = True
                        if control.mode == "active":
                            control.mode = "exit_only"
                            control.version += 1
                            actions.append({"action": "exit_only", "code": "DRAWDOWN_STOP"})

            check_drawdown(state)
            for order_id, order in list(state.orders.items()):
                if order.status != "open":
                    continue
                reason = None
                if control.mode == "halted" or mandate is None or expired:
                    reason = "Paper operations halted or mandate expired."
                elif order.intent.symbol not in mandate.allowed_symbols:
                    reason = "Instrument is outside the active mandate."
                elif control.mode == "exit_only" and order.intent.side == "buy":
                    reason = "Entry orders cancelled in exit-only mode."
                elif now - order.submitted_at >= timedelta(seconds=mandate.order_ttl_seconds):
                    reason = "Paper order expired under its mandate."
                elif not open_cases.get(order_id) or open_cases[order_id] in cancelled:
                    reason = "Originating decision is missing or its case was cancelled."
                if reason:
                    state = append(
                        PaperEvent(
                            idempotency_key="ops-cancel:" + str(uuid4()),
                            kind="order_cancelled",
                            occurred_at=now,
                            payload={"order_id": order_id, "reason": reason},
                        )
                    )
                    actions.append({"action": "cancelled", "order_id": order_id, "message": reason})
                    continue
                if market_open:
                    try:
                        state = append(
                            fill_order(
                                state,
                                order_id,
                                quotes[order.intent.symbol],
                                policy,
                                now,
                                idempotency_key="ops-fill:" + str(uuid4()),
                                portfolio_quotes=quotes,
                            )
                        )
                        actions.append({"action": "filled", "order_id": order_id})
                        check_drawdown(state)
                    except (PaperError, KeyError) as exc:
                        actions.append(
                            {
                                "action": "waiting",
                                "order_id": order_id,
                                "code": getattr(exc, "code", "QUOTE_REQUIRED"),
                            }
                        )
            if control.mode == "exit_only":
                for event in self._cancel_events(
                    [*events, *new_events],
                    lambda order: order.intent.side == "buy",
                    "Entry orders cancelled after a drawdown stop.",
                    now,
                ):
                    state = append(event)
                    actions.append(
                        {"action": "cancelled", "order_id": event["payload"]["order_id"]}
                    )
            if market_open and mandate and not expired and control.mode != "halted":
                for artifact, order in candidates:
                    if order.order_id in state.orders or artifact["case_id"] in cancelled:
                        continue
                    if control.mode == "exit_only" and order.side == "buy":
                        continue
                    decision_age = (
                        now - datetime.fromisoformat(artifact["created_at"])
                    ).total_seconds()
                    if not 0 <= decision_age <= mandate.max_decision_age_seconds:
                        continue
                    if (
                        sum(o.status == "open" for o in state.orders.values())
                        >= mandate.max_open_orders
                    ):
                        break
                    try:
                        state = append(
                            reserve_order(
                                state,
                                order,
                                policy,
                                quotes,
                                now,
                                idempotency_key="ops-reserve:" + order.order_id,
                            )
                        )
                        actions.append({"action": "reserved", "order_id": order.order_id})
                    except PaperError as exc:
                        actions.append(
                            {"action": "rejected", "order_id": order.order_id, "code": exc.code}
                        )
            self._append(session, account, events, new_events)
            for day in calendar:
                payload = MarketSession(
                    session=day.session, open_at=day.open, close_at=day.close
                ).model_dump(mode="json")
                existing = session.get(MarketSessionRow, str(day.session))
                if existing and existing.payload != payload:
                    # Keep the first observed session definition; revisions require review.
                    raise DomainError(
                        "CALENDAR_CHANGED",
                        "Retained session changed; review it before recording further results.",
                        409,
                    )
                if not existing:
                    session.add(MarketSessionRow(session=str(day.session), payload=payload))
            if calendar_range:
                coverage = {
                    "start": str(calendar_range[0]),
                    "end": str(calendar_range[1]),
                    "sessions": [str(day.session) for day in calendar],
                    "verified_at": now.isoformat(),
                }
                retained_coverage = session.get(SystemRow, "paper_calendar_coverage")
                if retained_coverage:
                    retained_coverage.value = coverage
                else:
                    session.add(SystemRow(key="paper_calendar_coverage", value=coverage))
            session.flush()
            self._observation(
                session,
                account,
                [*events, *new_events],
                quotes if failure is None else {},
                calendar,
                now,
                policy,
                bool(new_events),
            )
            status = (
                "data_blocked"
                if failure
                else "unconfigured"
                if not mandate
                else "halted"
                if control.mode == "halted"
                else "market_open"
                if market_open
                else "market_closed"
            )
            result = {
                "next_poll_seconds": self.next_poll_seconds(
                    now, calendar, mandate.poll_interval_seconds if mandate else 30
                ),
                "feed": self.provider.health(),
                "observed_at": now.isoformat(),
                "status": status,
                "actions": actions,
                "error": failure,
            }
            control.latest_tick = result
            control.last_seen_at = now.isoformat()
            control.worker_id, control.lease_until = None, None
            if quotes and failure is None:
                # Same commit as fills and observations; API portfolio gets these marks.
                retained = session.get(SystemRow, "paper_quotes")
                payload = {k: q.model_dump(mode="json") for k, q in quotes.items()}
                if retained:
                    retained.value = payload
                else:
                    session.add(SystemRow(key="paper_quotes", value=payload))
            return result

    def _observation(self, session, account, events, quotes, calendar, now, policy, force):
        state = replay(events)
        if state.account_id is None:
            return
        last = session.scalar(
            select(PaperObservationRow)
            .where(PaperObservationRow.account_id == ACCOUNT)
            .order_by(PaperObservationRow.seq.desc())
            .limit(1)
        )
        closing = any(day.close <= now <= day.close + timedelta(seconds=120) for day in calendar)
        interval = 15 if closing else 60
        if (
            last
            and not force
            and (now - datetime.fromisoformat(last.observed_at)).total_seconds() < interval
        ):
            return
        closing_session = next(
            (day for day in calendar if day.close <= now <= day.close + timedelta(seconds=120)),
            None,
        )
        valuation_policy = policy
        if closing_session:
            # Performance-only close-window mark; never relax order admission.
            allowance = int((now - closing_session.close).total_seconds()) + 60
            valuation_policy = policy.model_copy(update={"max_quote_age_seconds": allowance})
        missing = tuple(
            sorted(
                symbol
                for symbol in state.positions
                if symbol not in quotes
                or not 0
                <= (now - quotes[symbol].as_of).total_seconds()
                <= valuation_policy.max_quote_age_seconds
            )
        )
        try:
            equity = Decimal(mark_portfolio(state, quotes, now, valuation_policy)["equity"])
        except PaperError:
            equity = None
        held = [quotes[symbol].as_of for symbol in state.positions if symbol in quotes]
        market_session = next(
            (
                day.session
                for day in calendar
                if day.open <= now <= day.close + timedelta(seconds=120)
            ),
            None,
        )
        observation = ValuationObservation(
            observation_id=str(uuid4()),
            account_id=ACCOUNT,
            observed_at=now,
            account_opened_at=datetime.fromisoformat(events[0]["occurred_at"]),
            market_session=market_session,
            book_version=account.version,
            event_count=state.event_count,
            fill_count=sum(e["kind"] == "fill" for e in events),
            position_count=len(state.positions),
            initial_cash=state.initial_cash,
            cash=state.cash,
            realized_pnl=state.realized_pnl,
            fees=state.fees,
            equity=equity,
            oldest_quote_at=min(held) if held else None,
            missing_symbols=missing,
        )
        session.add(
            PaperObservationRow(
                account_id=ACCOUNT,
                observed_at=now.isoformat(),
                payload=observation.model_dump(mode="json"),
            )
        )

    @staticmethod
    def next_poll_seconds(now, calendar, requested):
        delay = float(requested)
        for day in calendar:
            until_close = (day.close - now).total_seconds()
            if 0 < until_close < delay:
                delay = until_close
            elif -120 <= until_close <= 0:
                delay = min(delay, 15)
        return max(0.1, delay)

    def performance(self):
        report_time = datetime.now(UTC)
        start = report_time - timedelta(days=7)
        first_day = start.astimezone(NY).date().isoformat()
        with Session(self.store.engine) as session:
            coverage_row = session.get(SystemRow, "paper_calendar_coverage")
            coverage = coverage_row.value if coverage_row else {}
            calendar = [
                row.payload
                for row in session.scalars(
                    select(MarketSessionRow)
                    .where(
                        MarketSessionRow.session >= coverage.get("start", "9999-12-31"),
                        MarketSessionRow.session <= coverage.get("end", "0000-01-01"),
                    )
                    .order_by(MarketSessionRow.session)
                )
            ]
            complete = bool(coverage) and {row["session"] for row in calendar} == set(
                coverage.get("sessions", [])
            )
            if not complete:
                calendar = []
            previous = [row for row in calendar if row["session"] < first_day]
            fetch_start = (
                min(start.isoformat(), previous[-1]["open_at"]) if previous else start.isoformat()
            )
            rows = list(
                session.scalars(
                    select(PaperObservationRow)
                    .where(
                        PaperObservationRow.account_id == ACCOUNT,
                        PaperObservationRow.observed_at >= fetch_start,
                    )
                    .order_by(PaperObservationRow.seq.desc())
                    .limit(12001)
                )
            )
            truncated = len(rows) > 12000
            observations = [row.payload for row in reversed(rows[:12000])]
        result = build_performance(observations, calendar, report_as_of=report_time)
        result["equity_series"] = [
            row for row in result["equity_series"] if row["observed_at"] >= start.isoformat()
        ]
        result["daily"] = [row for row in result["daily"] if row["session"] >= first_day]
        if result["latest"] and result["latest"]["observed_at"] < start.isoformat():
            result["latest"] = None
        result["calendar_coverage"] = {
            **{key: coverage.get(key) for key in ("start", "end", "verified_at")},
            "complete": complete,
            "reason": None
            if complete
            else "CALENDAR_COVERAGE_INCOMPLETE"
            if coverage
            else "CALENDAR_COVERAGE_MISSING",
        }
        result["window"] = {"days": 7, "max_observations": 12000, "truncated": truncated}
        return result

    def status(self):
        with Session(self.store.engine) as session:
            control = session.get(PaperControlRow, ACCOUNT)
            mandates = [
                row_dict(row)
                for row in session.scalars(
                    select(PaperMandateRow).order_by(PaperMandateRow.created_at.desc()).limit(100)
                )
            ]
            row = session.get(PaperMandateRow, control.mandate_id) if control.mandate_id else None
            latest = session.scalar(
                select(PaperObservationRow)
                .where(PaperObservationRow.account_id == ACCOUNT)
                .order_by(PaperObservationRow.seq.desc())
                .limit(1)
            )
            last_seen = (
                datetime.fromisoformat(control.last_seen_at) if control.last_seen_at else None
            )
            payload = self._mandate(row) if row else None
            threshold = max(
                30, (payload.poll_interval_seconds if payload else 30) * 2 + LEASE_SECONDS
            )
            return {
                "control": {
                    "version": control.version,
                    "mode": control.mode,
                    "mandate_id": control.mandate_id,
                },
                "mandate": row_dict(row) if row else None,
                "mandates": mandates,
                "feed": (control.latest_tick or {}).get("feed", self.provider.health())
                if last_seen and (datetime.now(UTC) - last_seen).total_seconds() < threshold
                else self.provider.health(),
                "worker": {
                    "active": bool(
                        last_seen and (datetime.now(UTC) - last_seen).total_seconds() < threshold
                    ),
                    "last_seen_at": control.last_seen_at,
                },
                "latest_observation": latest.payload if latest else None,
                "latest_tick": control.latest_tick,
                "drawdown": {
                    "peak_equity": control.peak_equity,
                    "tripped": control.drawdown_tripped,
                },
                "performance": self.performance(),
                "limitations": [
                    "Local quote-driven paper simulation; no broker orders.",
                    "Equities/ETFs only; no options, corporate actions or external cash flows.",
                    "Quote-driven fills approximate liquidity; no queue or market-impact model.",
                    "Drawdown stops entries; it does not cap losses or liquidate holdings.",
                    "Last seven days shown; missing closes and stale marks remain gaps.",
                    "Local worker scans the most recent 500 research intents.",
                ],
            }
