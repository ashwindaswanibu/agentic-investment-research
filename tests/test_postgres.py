"""Real PostgreSQL concurrency tests, isolated in disposable UUID schemas.

Set RESEARCHDESK_TEST_DATABASE_URL to an explicitly disposable test database.
Only the uniquely generated schema is dropped; no existing schema is modified.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.engine import make_url

from researchdesk.db import TaskRow
from researchdesk.errors import DomainError
from researchdesk.paper import PaperError, PaperEvent, PaperPolicy, Quote, replay, reserve_order
from researchdesk.store import Store

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_store():
    configured = os.environ.get("RESEARCHDESK_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("set RESEARCHDESK_TEST_DATABASE_URL for real PostgreSQL integration")
    url = make_url(configured)
    if url.get_backend_name() != "postgresql":
        pytest.fail("RESEARCHDESK_TEST_DATABASE_URL must identify PostgreSQL")
    schema = f"researchdesk_test_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    store = None
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        scoped = url.update_query_dict(
            {"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=15000"}
        )
        store = Store(scoped.render_as_string(hide_password=False))
        assert store.engine.dialect.name == "postgresql"
        yield store
    finally:
        if store is not None:
            store.close()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def race(count, action):
    barrier = threading.Barrier(count)

    def synchronized(index):
        barrier.wait(timeout=10)
        return action(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(synchronized, range(count)))


def test_postgres_competing_workers_claim_once(postgres_store):
    store = postgres_store
    case = store.create_case("Concurrent claim", "Synthetic worker ownership test")
    task = store.create_task(case["id"], "coordinator", "Inspect fixture")
    claims = race(12, lambda index: store.claim_task(f"worker-{index}"))
    assert [claim["id"] for claim in claims if claim] == [task["id"]]
    assert store.get_task(task["id"])["attempt"] == 1


def test_postgres_shared_budget_across_multiple_tasks_is_atomic(postgres_store):
    store = postgres_store
    case = store.create_case("Shared budget", "Synthetic case-wide budget test", tool_budget=3)
    parent = store.create_task(case["id"], "coordinator", "Delegate fixture research")
    store.claim_task("coordinator")
    tasks = [
        store.create_task(
            case["id"],
            "researcher",
            f"Assignment {i}",
            parent_id=parent["id"],
            worker_id="coordinator",
        )
        for i in range(3)
    ]
    calls = race(
        12,
        lambda index: store.begin_tool_call(
            tasks[index % 3]["id"], str(index), "lookup", {"query": index}
        ),
    )
    assert sum(call["status"] == "running" for call in calls) == 3
    assert sum(call["status"] == "blocked" for call in calls) == 9
    assert store.get_case(case["id"])["tool_calls_used"] == 3
    assert len(store.list_tool_calls(case_id=case["id"])) == 12


def test_postgres_duplicate_tool_claims_share_one_id_and_budget(postgres_store):
    store = postgres_store
    case = store.create_case("Retry", "Synthetic idempotency test", tool_budget=3)
    task = store.create_task(case["id"], "researcher", "Lookup fixture")
    calls = race(
        10, lambda _: store.begin_tool_call(task["id"], "same-call", "lookup", {"q": "same"})
    )
    assert len({call["id"] for call in calls}) == 1
    assert store.get_case(case["id"])["tool_calls_used"] == 1


def test_postgres_reclaimed_lease_fences_old_worker(postgres_store):
    store = postgres_store
    case = store.create_case("Lease recovery", "Synthetic ownership recovery test")
    task = store.create_task(case["id"], "researcher", "Inspect fixture")
    assert store.claim_task("old-worker")["id"] == task["id"]
    with store.transaction() as session:
        session.execute(
            update(TaskRow).where(TaskRow.id == task["id"]).values(lease_until=time.time() - 1)
        )
    claims = race(8, lambda index: store.claim_task(f"replacement-{index}"))
    claimed = [result for result in claims if result]
    assert len(claimed) == 1
    assert store.get_task(task["id"])["attempt"] == 2
    with pytest.raises(DomainError):
        store.put_artifact(
            case["id"], task["id"], "note", "Stale", "late output", worker_id="old-worker"
        )
    assert store.list_artifacts(case_id=case["id"]) == []


def test_postgres_cancellation_and_claim_race_is_terminal(postgres_store):
    store = postgres_store
    # Repeat with new records; every winner is either a lease subsequently
    # cancelled or no claim. Reverse lock ordering would deadlock here.
    for index in range(12):
        case = store.create_case(f"Cancellation {index}", "Synthetic lock-order test")
        task = store.create_task(case["id"], "researcher", "Inspect fixture")

        def action(worker, case_id=case["id"]):
            return store.claim_task("racing-worker") if worker == 0 else store.cancel_case(case_id)

        race(2, action)
        assert store.get_case(case["id"])["status"] == "cancelled"
        assert store.get_task(task["id"])["status"] == "cancelled"
        with pytest.raises(DomainError):
            store.put_artifact(
                case["id"], task["id"], "note", "Late", "discard", worker_id="racing-worker"
            )


def test_postgres_atomic_paper_reservations_do_not_overspend(postgres_store):
    store = postgres_store
    now = datetime.now(UTC)
    opening = PaperEvent(
        idempotency_key="open",
        kind="account_opened",
        occurred_at=now,
        payload={"account_id": "paper-main", "cash": "1000", "currency": "USD"},
    )
    store.ledger_transaction(
        "open", lambda _: [opening.model_dump(mode="json")], request={"cash": "1000"}
    )
    quote = Quote(
        symbol="TEST",
        bid="10",
        ask="10",
        as_of=now,
        source="Explicit synthetic PostgreSQL concurrency fixture",
        bid_size=100,
        ask_size=100,
    )

    def action(index):
        def admission(events):
            event = reserve_order(
                replay(events),
                {
                    "order_id": str(index),
                    "symbol": "TEST",
                    "side": "buy",
                    "quantity": 60,
                    "limit_price": "10",
                    "decision_id": "synthetic-review",
                },
                PaperPolicy(max_symbol_weight=1),
                {"TEST": quote},
                now,
                idempotency_key=f"order-{index}",
            )
            return [event.model_dump(mode="json")]

        try:
            store.ledger_transaction(f"order-{index}", admission, request={"order": index})
            return True
        except PaperError as exc:
            assert exc.code == "insufficient_cash"
            return False

    outcomes = race(12, action)
    assert sum(outcomes) == 1
    ledger = store.ledger_events()
    assert len(ledger) == 2
    assert replay(ledger).available_cash == Decimal("399.94")


def test_postgres_concurrent_account_open_is_idempotent(postgres_store):
    store = postgres_store
    now = datetime.now(UTC)
    event = PaperEvent(
        idempotency_key="opening",
        kind="account_opened",
        occurred_at=now,
        payload={"account_id": "paper-main", "cash": "1000", "currency": "USD"},
    )
    results = race(
        8,
        lambda _: store.ledger_transaction(
            "opening", lambda rows: [event.model_dump(mode="json")], request={"cash": "1000"}
        ),
    )
    assert len(results) == 8
    assert len(store.ledger_events()) == 1
    assert replay(store.ledger_events()).cash == 1000
