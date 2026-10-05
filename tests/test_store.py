from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from researchdesk.errors import DomainError
from researchdesk.paper import PaperEvent, PaperPolicy, Quote, replay, reserve_order
from researchdesk.store import Store


@pytest.fixture
def store(tmp_path):
    value = Store(f"sqlite:///{tmp_path}/research.db")
    yield value
    value.close()


def task(store, *, budget=40):
    case = store.create_case("Research", "Test meaningful concurrent work", tool_budget=budget)
    job = store.create_task(case["id"], "coordinator", "Evaluate competing hypotheses")
    return case, job


def test_only_one_worker_can_claim_a_task(store):
    _, job = task(store)
    with ThreadPoolExecutor(max_workers=12) as pool:
        claims = list(pool.map(lambda i: store.claim_task(f"worker-{i}"), range(12)))
    assert [c["id"] for c in claims if c] == [job["id"]]
    assert store.get_task(job["id"])["attempt"] == 1


def test_shared_budget_cannot_be_overspent_by_concurrent_calls(store):
    case, job = task(store, budget=3)
    with ThreadPoolExecutor(max_workers=12) as pool:
        calls = list(
            pool.map(
                lambda i: store.begin_tool_call(job["id"], str(i), "lookup", {"q": i}), range(12)
            )
        )
    assert sum(c["status"] == "running" for c in calls) == 3
    assert sum(c["status"] == "blocked" for c in calls) == 9
    assert store.get_case(case["id"])["tool_calls_used"] == 3


def test_tool_retry_replays_record_without_spending_again(store):
    case, job = task(store)
    call = store.begin_tool_call(job["id"], "same", "lookup", {"q": "a"})
    store.finish_tool_call(call["id"], "completed", result={"ok": True, "data": 3})
    again = store.begin_tool_call(job["id"], "same", "lookup", {"q": "a"})
    assert again["result"] == {"ok": True, "data": 3}
    assert store.get_case(case["id"])["tool_calls_used"] == 1
    with pytest.raises(DomainError, match="different arguments"):
        store.begin_tool_call(job["id"], "same", "lookup", {"q": "different"})


def test_idempotency_key_cannot_rewrite_content(store):
    case = store.create_case("First", "Initial hypothesis", idempotency_key="case-key")
    assert (
        store.create_case("First", "Initial hypothesis", idempotency_key="case-key")["id"]
        == case["id"]
    )
    with pytest.raises(DomainError, match="different input"):
        store.create_case("Second", "Other hypothesis", idempotency_key="case-key")
    original = store.put_artifact(
        case["id"], None, "note", "Finding", "first", idempotency_key="artifact-key"
    )
    with pytest.raises(DomainError):
        store.put_artifact(
            case["id"], None, "note", "Finding", "rewritten", idempotency_key="artifact-key"
        )
    assert store.get_artifact(original["id"])["content"] == "first"


def test_cancellation_is_terminal_even_if_worker_never_returns(store):
    case, job = task(store)
    store.claim_task("worker")
    store.cancel_case(case["id"])
    assert store.get_task(job["id"])["status"] == "cancelled"
    assert store.claim_task("replacement") is None
    with pytest.raises(DomainError, match="no longer owns"):
        store.put_artifact(
            case["id"], job["id"], "note", "Late", "stale result", worker_id="worker"
        )


def test_coordinator_completion_updates_case_and_events(store):
    case, job = task(store)
    store.claim_task("worker")
    store.update_task(
        job["id"], worker_id="worker", status="completed", summary="Evidence is inconclusive"
    )
    assert store.get_case(case["id"])["status"] == "completed"
    assert store.get_case(case["id"])["summary"] == "Evidence is inconclusive"
    events = store.list_events(case["id"])
    assert len({e["seq"] for e in events}) == len(events)
    assert all(
        e["seq"] > events[1]["seq"] for e in store.list_events(case["id"], after=events[1]["seq"])
    )


def test_atomic_ledger_reservations_cannot_spend_same_cash_twice(store):
    now = datetime.now(UTC)
    opening = PaperEvent(
        idempotency_key="open",
        kind="account_opened",
        occurred_at=now,
        payload={"account_id": "paper-main", "cash": "1000", "currency": "USD"},
    ).model_dump(mode="json")
    store.ledger_transaction("open", lambda events: [opening], request={"cash": "1000"})
    quote = Quote(
        symbol="TEST",
        bid="10",
        ask="10",
        bid_size=100,
        ask_size=100,
        as_of=now,
        source="explicit synthetic test",
    )

    def attempt(index):
        def apply(events):
            event = reserve_order(
                replay(events),
                {
                    "order_id": str(index),
                    "symbol": "TEST",
                    "side": "buy",
                    "quantity": 60,
                    "limit_price": "10",
                    "decision_id": "test",
                },
                PaperPolicy(max_symbol_weight="1"),
                {"TEST": quote},
                now,
                idempotency_key=f"order-{index}",
            )
            return [event.model_dump(mode="json")]

        try:
            store.ledger_transaction(f"order-{index}", apply, request={"order": index})
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(attempt, range(8)))
    assert sum(admitted) == 1
    assert replay(store.ledger_events()).available_cash == Decimal("399.9400")
    with pytest.raises(DomainError, match="different paper action"):
        store.ledger_transaction("open", lambda events: [], request={"cash": "2000"})
