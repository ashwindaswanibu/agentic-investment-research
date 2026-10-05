"""Application transaction regressions with real SQLite Store and synthetic inputs."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import researchdesk.service as service_module
from researchdesk.errors import DomainError
from researchdesk.paper import PaperError, PaperEvent, PaperPolicy, Quote, replay, reserve_order
from researchdesk.service import PaperService
from researchdesk.store import Store

T = datetime(2025, 1, 1, 12, tzinfo=UTC)


class ControlledClock:
    value = T

    @classmethod
    def now(cls, tz):
        return cls.value.astimezone(tz)


class ReviewedFixture:
    """Review validation is tested in domain tests; isolate transaction timing here."""

    def __init__(self, case_id):
        self.case_id = case_id

    def artifact(self, identifier, **kwargs):
        return {
            "id": identifier,
            "case_id": self.case_id,
            "kind": "paper_intent",
            "content": {
                "artifact_id": "experiment",
                "review_id": "review",
                "symbol": "TEST",
                "side": "buy",
                "quantity": 10,
                "limit_price": "10",
            },
        }

    def validate_decision(self, *args, **kwargs):
        return None


@pytest.fixture
def fixture_service(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path}/service.db")
    case = store.create_case("Synthetic paper intent", "Transaction ordering fixture")
    service = PaperService(store, ReviewedFixture(case["id"]))
    monkeypatch.setattr(service_module, "datetime", ControlledClock)
    ControlledClock.value = T
    service.open_account(Decimal("1000"), "opening")
    yield service, store, case
    store.close()


def quote(at=T):
    return {
        "TEST": Quote(
            symbol="TEST",
            bid="10",
            ask="10",
            as_of=at,
            source="Explicit synthetic service-test quote",
            bid_size=100,
            ask_size=100,
        )
    }


def delayed_transaction(store, monkeypatch, delayed_key):
    original = store.ledger_transaction
    reached = threading.Event()
    release = threading.Event()

    def transaction(key, callback, **kwargs):
        if key == delayed_key:
            reached.set()
            assert release.wait(timeout=10)
        return original(key, callback, **kwargs)

    monkeypatch.setattr(store, "ledger_transaction", transaction)
    return reached, release


@pytest.mark.parametrize("operation", ["reserve", "fill"])
def test_timestamp_is_assigned_after_account_lock_not_at_request_start(
    fixture_service, monkeypatch, operation
):
    service, store, _ = fixture_service
    if operation == "fill":
        ControlledClock.value = T + timedelta(seconds=1)
        service.reserve("slow-intent", quote(), "reserve-slow")
        service.reserve("fast-intent", quote(), "reserve-fast")
    quotes = quote(T + timedelta(seconds=2))
    reached, release = delayed_transaction(store, monkeypatch, "delayed-request")

    def perform(intent, key):
        method = service.reserve if operation == "reserve" else service.fill
        return method(intent, quotes, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        ControlledClock.value = T + timedelta(seconds=3)
        slow = pool.submit(perform, "slow-intent", "delayed-request")
        assert reached.wait(timeout=10)
        ControlledClock.value = T + timedelta(seconds=4)
        fast = pool.submit(perform, "fast-intent", "fast-request")
        fast.result(timeout=10)
        ControlledClock.value = T + timedelta(seconds=5)
        release.set()
        slow.result(timeout=10)
    events = store.ledger_events()
    assert events[-2]["idempotency_key"] == "fast-request"
    assert events[-1]["idempotency_key"] == "delayed-request"
    assert events[-2]["occurred_at"] < events[-1]["occurred_at"]
    state = replay(events)
    assert state.event_count == len(events)


def test_invalid_candidate_event_stream_rolls_back_all_appended_events(fixture_service):
    _, store, _ = fixture_service
    before = store.ledger_events()
    good = reserve_order(
        replay(before),
        {
            "order_id": "new",
            "symbol": "TEST",
            "side": "buy",
            "quantity": 10,
            "limit_price": "10",
            "decision_id": "fixture",
        },
        PaperPolicy(),
        quote(),
        T + timedelta(seconds=1),
        idempotency_key="good",
    )
    backwards = PaperEvent(
        kind="order_cancelled",
        idempotency_key="bad",
        occurred_at=T,
        payload={"order_id": "new", "reason": "Invalid timestamp fixture"},
    )
    with pytest.raises(PaperError) as error:
        store.ledger_transaction(
            "batch",
            lambda _: [good.model_dump(mode="json"), backwards.model_dump(mode="json")],
            request={"action": "invalid-batch"},
        )
    assert error.value.code == "event_order"
    assert store.ledger_events() == before
    assert replay(store.ledger_events()).available_cash == 1000


def test_cancellation_between_request_precheck_and_transaction_blocks_admission(
    fixture_service, monkeypatch
):
    service, store, case = fixture_service
    reached, release = delayed_transaction(store, monkeypatch, "cancel-race")
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(service.reserve, "intent", quote(), "cancel-race")
        assert reached.wait(timeout=10)
        store.cancel_case(case["id"])
        release.set()
        with pytest.raises(DomainError) as error:
            request.result(timeout=10)
    assert error.value.code == "CANCELLED"
    assert len(store.ledger_events()) == 1
    assert replay(store.ledger_events()).orders == {}
