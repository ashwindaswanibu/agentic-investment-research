"""Real PostgreSQL locks with synthetic markets, never brokerage calls or returns.

The shared PostgreSQL fixture creates and drops only a random disposable schema.
Set RESEARCHDESK_TEST_DATABASE_URL to the explicitly disposable test database.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_paper_operations import (
    Clock,
    ReviewedDecisions,
    SyntheticMarket,
    T,
    activate,
    intent,
    mandate,
)
from test_postgres import postgres_store as postgres_store

import researchdesk.paper_operations as module
from researchdesk.db import AccountRow, PaperControlRow, PaperObservationRow, SystemRow
from researchdesk.errors import DomainError
from researchdesk.paper import PaperEvent, replay
from researchdesk.paper_operations import ACCOUNT, ControlInput, PaperOperations

pytestmark = pytest.mark.integration


@pytest.fixture
def operations(postgres_store, monkeypatch):
    Clock.value = T
    monkeypatch.setattr(module, "datetime", Clock)
    market = SyntheticMarket()
    ops = PaperOperations(postgres_store, ReviewedDecisions(postgres_store), market)
    opening = PaperEvent(
        kind="account_opened",
        occurred_at=T - timedelta(minutes=1),
        idempotency_key="pg-fixture-opening",
        payload={"account_id": ACCOUNT, "cash": "1000", "currency": "USD"},
    ).model_dump(mode="json")
    postgres_store.ledger_transaction("pg-fixture-opening", lambda _: [opening])
    case = postgres_store.create_case("PostgreSQL operations fixture", "Synthetic boundary test")
    saved = ops.create_mandate(mandate(), "pg-fixture-mandate")
    return ops, postgres_store, market, case, saved


def concurrently(count, action):
    barrier = threading.Barrier(count)

    def run(index):
        barrier.wait(timeout=10)
        return action(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def retained(store):
    """Capture actual committed financial, valuation and worker result records."""
    with Session(store.engine) as session:
        control = session.get(PaperControlRow, ACCOUNT)
        quotes = session.get(SystemRow, "paper_quotes")
        return {
            "version": session.get(AccountRow, ACCOUNT).version,
            "observations": session.scalar(select(func.count()).select_from(PaperObservationRow)),
            "quotes": quotes.value if quotes else None,
            "latest_tick": control.latest_tick,
            "peak_equity": control.peak_equity,
            "drawdown_tripped": control.drawdown_tripped,
        }


def test_postgres_operations_claim_once_and_fence_replaced_worker(operations):
    ops, store, _, _, _ = operations
    claims = concurrently(8, lambda i: ops.claim(f"paper-worker-{i}"))
    assert sum(token is not None for token in claims) == 1
    original = next(token for token in claims if token is not None)
    assert original["fence"] == 1
    Clock.value += timedelta(seconds=121)
    replacement = ops.claim("replacement")
    assert replacement["fence"] == original["fence"] + 1
    before = store.ledger_events()
    with pytest.raises(DomainError) as error:
        ops._commit_tick(original, None, [], [], {}, [], None, None)
    assert error.value.code == "PAPER_LEASE_LOST"
    assert store.ledger_events() == before
    with store.transaction() as session:
        assert ops._fenced(session, replacement).worker_id == "replacement"


def test_postgres_control_compare_and_swap_has_exactly_one_winner(operations):
    ops, _, _, _, saved = operations

    def change(index):
        try:
            return ops.set_control(
                ControlInput(
                    mandate_id=saved["id"],
                    mode="active" if index % 2 else "exit_only",
                    expected_version=0,
                )
            )
        except DomainError as error:
            return error.code

    results = concurrently(8, change)
    winners = [result for result in results if isinstance(result, dict)]
    assert len(winners) == 1
    assert results.count("CONTROL_CONFLICT") == 7
    assert winners[0]["version"] == 1
    assert ops.status()["control"] == winners[0]


def test_postgres_halt_during_quote_fetch_cancels_reservation_and_fences_fill(operations):
    ops, store, market, case, saved = operations
    order_id = intent(store, case)
    activate(ops, saved)
    ops.tick("initial-reservation")
    before = retained(store)
    reached, release = threading.Event(), threading.Event()

    def slow_quote():
        reached.set()
        assert release.wait(timeout=10)

    market.on_quotes = slow_quote
    Clock.value += timedelta(seconds=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(ops.tick, "slow-fill-worker")
        try:
            assert reached.wait(timeout=10)
            # This must finish while the worker is awaiting market data, proving
            # network reads do not hold the control/account transaction locks.
            halted = ops.set_control(
                ControlInput(mandate_id=saved["id"], mode="halted", expected_version=1)
            )
        finally:
            release.set()
        with pytest.raises(DomainError) as error:
            running.result(timeout=10)
    assert error.value.code == "PAPER_LEASE_LOST"
    assert halted["mode"] == "halted"
    state = replay(store.ledger_events())
    assert state.cash == 1000 and state.positions == {} and state.reserved_cash == 0
    assert state.orders[order_id].status == "cancelled"
    assert [event["kind"] for event in store.ledger_events()] == [
        "account_opened",
        "order_reserved",
        "order_cancelled",
    ]
    after = retained(store)
    assert after["observations"] == before["observations"]
    assert after["quotes"] == before["quotes"]


def test_postgres_failed_observation_rolls_back_flushed_fill_then_retry_commits_once(
    operations, monkeypatch
):
    ops, store, _, case, saved = operations
    order_id = intent(store, case)
    activate(ops, saved)
    ops.tick("initial-reservation")
    before_events, before = store.ledger_events(), retained(store)
    original_observation = ops._observation

    def fail_after_flush(*args, **kwargs):
        raise RuntimeError("Injected failure after ledger flush, before observation commit")

    monkeypatch.setattr(ops, "_observation", fail_after_flush)
    Clock.value += timedelta(seconds=1)
    with pytest.raises(RuntimeError, match="after ledger flush"):
        ops.tick("failed-fill-worker")
    assert store.ledger_events() == before_events
    assert retained(store) == before
    assert replay(store.ledger_events()).orders[order_id].remaining == 10

    monkeypatch.setattr(ops, "_observation", original_observation)
    # An explicit control change fences the failed lease without waiting for its
    # timeout. It neither cancels this order nor resets the account's book.
    activate(ops, saved)
    Clock.value += timedelta(seconds=1)
    ops.tick("replacement-fill-worker")
    state = replay(store.ledger_events())
    assert state.positions["TEST"].quantity == 5
    assert state.cash == 950 and state.orders[order_id].remaining == 5
    assert sum(event["kind"] == "fill" for event in store.ledger_events()) == 1
    assert retained(store)["observations"] == before["observations"] + 1
