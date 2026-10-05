"""Deterministic paper admission around immutable, reviewed research decisions."""

from datetime import UTC, datetime
from decimal import Decimal

from researchdesk.domain import ResearchTools
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


class PaperService:
    def __init__(self, store, research: ResearchTools):
        self.store, self.research = store, research
        self.policy = PaperPolicy()

    def open_account(self, cash: Decimal, key):
        def apply(events):
            if events:
                raise DomainError("ACCOUNT_EXISTS", "The paper account is already open.", 409)
            return [
                PaperEvent(
                    idempotency_key=key,
                    kind="account_opened",
                    occurred_at=datetime.now(UTC),
                    payload={"account_id": "paper-main", "cash": str(cash), "currency": "USD"},
                ).model_dump(mode="json")
            ]

        return self.store.ledger_transaction(
            key, apply, request={"action": "open", "cash": str(cash)}
        )

    def reserve(self, intent_id, quotes, key):
        intent = self.research.artifact(intent_id, kind="paper_intent")
        content = intent["content"]
        self.research.validate_decision(
            content["artifact_id"], content["review_id"], case_id=intent["case_id"]
        )
        if self.store.get_case(intent["case_id"])["status"] == "cancelled":
            raise DomainError("CANCELLED", "This research decision was cancelled.", 409)
        order = OrderIntent(
            order_id=intent_id,
            decision_id=intent_id,
            **{k: content[k] for k in ("symbol", "side", "quantity", "limit_price")},
        )

        def apply(events):
            observed_at = datetime.now(UTC)
            event = reserve_order(
                replay(events), order, self.policy, quotes, observed_at, idempotency_key=key
            )
            return [event.model_dump(mode="json")]

        result = self.store.ledger_transaction(
            key,
            apply,
            case_id=intent["case_id"],
            request={
                "action": "reserve",
                "intent_id": intent_id,
                "quotes": {k: v.model_dump(mode="json") for k, v in quotes.items()},
            },
        )
        self._retain_quotes(quotes)
        return result

    def fill(self, order_id, quotes, key):
        decision = self.research.artifact(order_id, kind="paper_intent")

        def apply(events):
            now = datetime.now(UTC)
            state = replay(events)
            if order_id not in state.orders:
                raise DomainError("ORDER_NOT_FOUND", "No reserved order has this ID.", 404)
            intent = self.research.artifact(
                state.orders[order_id].intent.decision_id, kind="paper_intent"
            )
            if self.store.get_case(intent["case_id"])["status"] == "cancelled":
                raise DomainError("CANCELLED", "The originating research case was cancelled.", 409)
            symbol = state.orders[order_id].intent.symbol
            if symbol not in quotes:
                raise DomainError(
                    "QUOTE_REQUIRED", "Provide a current quote for the order instrument."
                )
            return [
                fill_order(
                    state,
                    order_id,
                    quotes[symbol],
                    self.policy,
                    now,
                    idempotency_key=key,
                    portfolio_quotes=quotes,
                ).model_dump(mode="json")
            ]

        result = self.store.ledger_transaction(
            key,
            apply,
            case_id=decision["case_id"],
            request={
                "action": "fill",
                "order_id": order_id,
                "quotes": {k: v.model_dump(mode="json") for k, v in quotes.items()},
            },
        )
        self._retain_quotes(quotes)
        return result

    def cancel(self, order_id, key):
        def apply(events):
            state = replay(events)
            if order_id not in state.orders or state.orders[order_id].status != "open":
                raise DomainError(
                    "ORDER_NOT_OPEN", "Cancellation requires an open paper order.", 409
                )
            result = PaperEvent(
                idempotency_key=key,
                kind="order_cancelled",
                occurred_at=datetime.now(UTC),
                payload={"order_id": order_id, "reason": "Operator cancelled the paper order."},
            ).model_dump(mode="json")
            replay([*events, result])
            return [result]

        return self.store.ledger_transaction(
            key, apply, request={"action": "cancel", "order_id": order_id}
        )

    def _retain_quotes(self, quotes):
        # Last observation is useful for valuation only while fresh. Fill evidence
        # is retained independently in immutable ledger events.
        self.store.set_system(
            "paper_quotes", {k: q.model_dump(mode="json") for k, q in quotes.items()}
        )

    def portfolio(self):
        events = self.store.ledger_events()
        state = replay(events)
        quotes = self.store.get_system("paper_quotes") or {}
        try:
            result = mark_portfolio(state, quotes, datetime.now(UTC), self.policy)
        except PaperError:
            result = state.as_dict()
            result.update(
                equity=None,
                total_pnl=None,
                valuation_basis="unavailable: current attributable quotes required",
                positions=[
                    {
                        "symbol": s,
                        "quantity": p.quantity,
                        "cost_basis": str(p.cost_basis),
                        "mark": None,
                        "market_value": None,
                        "unrealized_pnl": None,
                    }
                    for s, p in state.positions.items()
                ],
            )
        result.update(
            events=events,
            policy=self.policy.model_dump(mode="json"),
            initialized=state.account_id is not None,
        )
        return result
