from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import update

from researchdesk.agents.registry import ToolContext
from researchdesk.api import create_app
from researchdesk.config import Settings
from researchdesk.db import ArtifactRow, TaskRow
from researchdesk.domain import ResearchTools
from researchdesk.errors import DomainError
from researchdesk.forecast_workflow import (
    ForecastInput,
    ResolutionInput,
    list_forecasts,
    register_forecast,
    resolve_forecast,
)
from researchdesk.store import Store, content_hash


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path}/forecast.db")
    research = ResearchTools(store, Settings(_env_file=None))
    case = store.create_case("Forecast research", "Will the declared event be reported?")
    source = store.put_artifact(
        case["id"],
        None,
        "evidence",
        "Research source",
        {"text": "Engineering fixture only."},
        {"synthetic": True},
    )
    hypothesis = store.put_artifact(
        case["id"],
        None,
        "hypothesis",
        "Exact saved hypothesis",
        {"prediction": "The declared event occurs.", "source_artifact_ids": [source["id"]]},
        {"inputs": [{"id": source["id"], "sha256": source["sha256"]}]},
    )

    class Clock(datetime):
        instant = datetime.now(UTC) + timedelta(seconds=1)

        @classmethod
        def now(cls, tz=None):
            return cls.instant if tz else cls.instant.replace(tzinfo=None)

    monkeypatch.setattr("researchdesk.store.datetime", Clock)
    monkeypatch.setattr("researchdesk.forecast_workflow.datetime", Clock)
    values = {
        "hypothesis_id": hypothesis["id"],
        "hypothesis_sha256": hypothesis["sha256"],
        "question": "Will the reported fixture satisfy the declared success rule?",
        "opens_at": (Clock.instant + timedelta(seconds=10)).isoformat(),
        "closes_at": (Clock.instant + timedelta(seconds=20)).isoformat(),
        "yes_rule": "A retained report explicitly records success during the window.",
        "no_rule": "A retained report explicitly records failure during the window.",
        "unresolvable_rule": "No available report supports either declared outcome.",
        "resolution_source": "The retained fixture report and its publication record.",
        "status": "forecast",
        "probability": 0.7,
        "baseline_probability": 0.5,
        "baseline_rationale": "A fixed engineering comparison, not estimated population odds.",
        "source_artifact_ids": [source["id"]],
    }
    yield store, research, case, source, hypothesis, values, Clock
    store.close()


def register(env, key="forecast-key", **changes):
    _, research, case, _, _, values, _ = env
    return register_forecast(research, {**values, **changes}, case_id=case["id"], key=key)


def evidence(env, content=None, **metadata):
    store, _, case, _, _, _, _ = env
    return store.put_artifact(
        case["id"],
        None,
        "evidence",
        "Retained outcome report",
        content
        if content is not None
        else {
            "report": "Success was reported during the window.",
            "failure": "Failure was reported during the window.",
            "missing": None,
        },
        metadata,
    )


def resolution(source, **changes):
    return {
        "outcome": "yes",
        "rationale": "The cited report satisfies the declared yes rule.",
        "source_refs": [
            {
                "artifact_id": source["id"],
                "artifact_sha256": source["sha256"],
                "excerpt": "Success was reported during the window.",
                "source_path": "/report",
            }
        ],
        **changes,
    }


def close_window(env):
    env[-1].instant = datetime.fromisoformat(env[5]["closes_at"])


def context(env, role="researcher", call="register-call"):
    store, _, case, *_ = env
    task = store.create_task(case["id"], role, "Register an exact forecast")
    store.claim_task("forecast-worker")
    return ToolContext(store, case["id"], task["id"], call, "forecast-worker", lambda: False)


def test_registration_records_exact_hypothesis_server_time_and_sources(env):
    store, research, case, source, hypothesis, values, clock = env
    saved = register(env)
    content = saved["content"]
    assert content["registered_at"] == clock.instant.isoformat()
    assert content["hypothesis"]["id"] == hypothesis["id"]
    assert content["hypothesis"]["sha256"] == hypothesis["sha256"]
    assert content["source_refs"][0]["sha256"] == source["sha256"]
    assert content["synthetic"] and saved["metadata"]["synthetic"]
    assert content["execution_eligible"] is False
    assert saved["metadata"]["execution_eligible"] is False
    assert saved["sha256"] == content_hash(content)
    assert list_forecasts(research, case["id"])["items"][0]["assessment"]["status"] == "pending"
    clock.instant += timedelta(days=1)
    # A late identical retry recovers the original registration time and hash.
    assert register(env) == saved
    with pytest.raises(DomainError, match="different input"):
        register(env, probability=0.8)
    assert len(store.list_forecast_artifacts(case["id"])) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"probability": None},
        {"probability": True},
        {"probability": "0.7"},
        {"probability": -0.1},
        {"probability": 1.1},
        {"probability": float("nan")},
        {"baseline_probability": False},
        {"baseline_probability": float("inf")},
        {"abstention_reason": "Unexpected reason"},
        {"status": "abstain", "probability": None},
        {"status": "abstain", "abstention_reason": "Unsupported odds"},
        {"question": " "},
        {"yes_rule": " "},
        {"baseline_rationale": " "},
        {"opens_at": "2030-01-01T00:00:00"},
        {"opens_at": 123456},
        {"source_artifact_ids": []},
        {"registered_at": "2000-01-01T00:00:00Z"},
    ],
)
def test_invalid_contracts_are_rejected(env, change):
    with pytest.raises(ValidationError):
        ForecastInput.model_validate({**env[5], **change})


@pytest.mark.parametrize("probability", [0, 1])
def test_endpoints_are_valid_probabilities(env, probability):
    assert register(env, probability=probability)["content"]["probability"] == probability


def test_window_hash_case_and_source_kinds_are_enforced(env):
    store, _, case, _, hypothesis, values, clock = env
    with pytest.raises(DomainError) as error:
        register(env, opens_at=clock.instant.isoformat())
    assert error.value.code == "FORECAST_WINDOW"
    with pytest.raises(ValidationError):
        register(env, closes_at=values["opens_at"])
    with pytest.raises(DomainError) as error:
        register(env, hypothesis_sha256="0" * 64)
    assert error.value.code == "HYPOTHESIS_HASH"
    other = store.create_case("Another case", "Unrelated case hypothesis")
    foreign = store.put_artifact(other["id"], None, "evidence", "Other source", "Report")
    protected = store.put_artifact(case["id"], None, "evaluation_reference", "Protected", {})
    for source, code in [
        (foreign, "ARTIFACT_CASE"),
        (protected, "PROTECTED_EVALUATION"),
        (hypothesis, "ARTIFACT_TYPE"),
    ]:
        with pytest.raises(DomainError) as error:
            register(env, source_artifact_ids=[source["id"]])
        assert error.value.code == code
    with pytest.raises(DomainError) as error:
        register(env, hypothesis_id=foreign["id"], hypothesis_sha256=foreign["sha256"])
    assert error.value.code == "ARTIFACT_CASE"


@pytest.mark.parametrize(
    "timestamp", ["received_at", "retrieved_at", "acquisition_started_at", "created_at"]
)
@pytest.mark.parametrize("location", ["content", "metadata", "artifact"])
def test_future_source_times_are_rejected(env, timestamp, location):
    if location == "artifact" and timestamp != "created_at":
        pytest.skip("Only retention created_at is an artifact column")
    store, _, _, _, _, _, clock = env
    future = (clock.instant + timedelta(days=1)).isoformat()
    source = evidence(
        env,
        {timestamp: future} if location == "content" else None,
        **({timestamp: future} if location == "metadata" else {}),
    )
    if location == "artifact":
        with store.transaction() as session:
            session.execute(
                update(ArtifactRow).where(ArtifactRow.id == source["id"]).values(created_at=future)
            )
    with pytest.raises(DomainError) as error:
        register(env, source_artifact_ids=[source["id"]])
    assert error.value.code == "INPUT_AFTER_REGISTRATION"


def test_deadline_is_rechecked_after_flush_and_rolls_back_atomically(env, monkeypatch):
    store, _, case, _, _, values, clock = env
    emit = store._event

    def delayed_event(*args, **kwargs):
        value = emit(*args, **kwargs)
        clock.instant = datetime.fromisoformat(values["opens_at"])
        return value

    monkeypatch.setattr(store, "_event", delayed_event)
    with pytest.raises(DomainError) as error:
        register(env)
    assert error.value.code == "FORECAST_WINDOW"
    assert not store.list_forecast_artifacts(case["id"])
    assert not [
        event for event in store.list_events(case["id"]) if event["data"].get("kind") == "forecast"
    ]


def test_resolution_is_due_only_then_scores_and_preserves_correction_history(env):
    _, research, case, _, _, _, _ = env
    forecast = register(env)
    source = evidence(env)
    args = resolution(source)
    with pytest.raises(DomainError) as error:
        resolve_forecast(research, forecast["id"], args, key="first-resolution")
    assert error.value.code == "FORECAST_NOT_DUE"
    close_window(env)
    assert list_forecasts(research, case["id"])["items"][0]["assessment"]["status"] == "due"
    first = resolve_forecast(research, forecast["id"], args, key="first-resolution")
    item = list_forecasts(research, case["id"])["items"][0]
    assert item["assessment"]["brier"] == pytest.approx(0.09)
    assert item["assessment"]["baseline_brier"] == 0.25
    assert item["assessment"]["improvement"] == pytest.approx(0.16)
    assert first["content"]["resolver_origin"] == "operator_api"
    assert first["content"]["synthetic"] and not first["content"]["execution_eligible"]
    correction = resolution(source, outcome="no", previous_resolution_id=first["id"])
    correction["source_refs"][0].update(
        source_path="/failure", excerpt="Failure was reported during the window."
    )
    second = resolve_forecast(research, forecast["id"], correction, key="correction-key")
    assert second["content"]["previous_resolution"]["sha256"] == first["sha256"]
    assert second["content"]["revision"] == 2
    assert resolve_forecast(research, forecast["id"], args, key="first-resolution") == first
    with pytest.raises(DomainError) as error:
        resolve_forecast(research, forecast["id"], args, key="stale-initial")
    assert error.value.code == "RESOLUTION_CONFLICT"
    item = list_forecasts(research, case["id"])["items"][0]
    assert item["resolutions"] == [first, second]
    assert item["forecast"] == forecast and item["latest_resolution"] == second
    assert item["assessment"]["brier"] == pytest.approx(0.49)
    assert item["assessment"]["improvement"] == pytest.approx(-0.24)


def test_unresolvable_requires_actual_retained_missingness_and_never_scores(env):
    _, research, case, _, _, _, _ = env
    forecast = register(env)
    close_window(env)
    source = evidence(env)
    args = resolution(source, outcome="unresolvable", rationale="The retained field is null.")
    args["source_refs"][0].update(source_path="/missing", excerpt="null")
    saved = resolve_forecast(research, forecast["id"], args, key="unresolvable-key")
    item = list_forecasts(research, case["id"])["items"][0]
    assert saved["content"]["outcome"] == "unresolvable"
    assert item["assessment"] == {
        "status": "unresolvable",
        "scored": False,
        "brier": None,
        "baseline_brier": None,
        "improvement": None,
        "execution_eligible": False,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_sha256": "0" * 64},
        {"excerpt": "This invented excerpt is absent."},
        {"source_path": "/absent", "excerpt": "null"},
        {"source_path": "", "excerpt": '{"report": "Success was reported during the window."}'},
        {"source_path": "/missing", "excerpt": "unavailable"},
    ],
)
def test_resolution_citations_fail_closed(env, change):
    _, research, case, _, _, _, _ = env
    forecast = register(env)
    close_window(env)
    args = resolution(evidence(env), outcome="unresolvable")
    args["source_refs"][0].update(change)
    with pytest.raises(DomainError) as error:
        resolve_forecast(research, forecast["id"], args, key="bad-citation")
    assert error.value.code == "RESOLUTION_SOURCE"
    assert not list_forecasts(research, case["id"])["items"][0]["resolutions"]


def test_resolution_future_foreign_protected_and_wrong_previous_are_rejected(env):
    store, research, case, _, _, _, clock = env
    forecast = register(env)
    close_window(env)
    other = store.create_case("Another case", "Unrelated evidence cannot resolve this event")
    foreign = store.put_artifact(other["id"], None, "evidence", "Foreign report", {"report": "Yes"})
    protected = store.put_artifact(case["id"], None, "evaluation_report", "Protected report", {})
    future = evidence(env, {"received_at": (clock.instant + timedelta(seconds=1)).isoformat()})
    for source, code in [
        (foreign, "ARTIFACT_CASE"),
        (protected, "PROTECTED_EVALUATION"),
        (future, "INPUT_AFTER_REGISTRATION"),
    ]:
        with pytest.raises(DomainError) as error:
            resolve_forecast(research, forecast["id"], resolution(source), key="invalid-source")
        assert error.value.code == code
    with pytest.raises(DomainError) as error:
        resolve_forecast(
            research,
            forecast["id"],
            resolution(evidence(env), previous_resolution_id=forecast["id"]),
            key="invalid-previous",
        )
    assert error.value.code == "RESOLUTION_CONFLICT"


def test_abstention_has_no_probability_and_never_scores_even_if_resolved(env):
    _, research, case, _, _, _, _ = env
    forecast = register(
        env,
        status="abstain",
        probability=None,
        abstention_reason="Evidence does not support defensible odds.",
    )
    close_window(env)
    resolve_forecast(research, forecast["id"], resolution(evidence(env)), key="abstain-resolution")
    item = list_forecasts(research, case["id"])["items"][0]
    assert item["latest_resolution"] and item["assessment"]["status"] == "abstained"
    assert not item["assessment"]["scored"] and item["assessment"]["brier"] is None


def test_readonly_cancelled_and_lost_lease_fence_writes(env):
    store, research, case, _, _, _, _ = env
    forecast = register(env)
    close_window(env)
    args = resolution(evidence(env))
    research.settings.read_only = True
    with pytest.raises(DomainError) as error:
        resolve_forecast(research, forecast["id"], args, key="readonly")
    assert error.value.code == "READ_ONLY"
    with pytest.raises(DomainError) as error:
        register(env)
    assert error.value.code == "READ_ONLY"
    research.settings.read_only = False
    store.cancel_case(case["id"])
    for operation in [
        lambda: register(env),
        lambda: resolve_forecast(research, forecast["id"], args, key="cancelled"),
    ]:
        with pytest.raises(DomainError) as error:
            operation()
        assert error.value.code == "CANCELLED"


def test_agent_roles_recovery_and_cancellation(env, monkeypatch):
    store, research, case, _, _, values, _ = env
    registry = research.registry()
    assert "register_forecast" in registry.allowed_names("researcher")
    assert "register_forecast" in registry.allowed_names("coordinator")
    assert "register_forecast" not in registry.allowed_names("coder")
    assert "register_forecast" not in registry.allowed_names("reviewer")
    assert "resolve_forecast" not in registry
    ctx = context(env)
    store.begin_tool_call(
        ctx.task_id, ctx.call_id, "register_forecast", values, worker_id=ctx.worker_id
    )
    first = registry.execute("register_forecast", values, ctx)
    assert first["ok"], first
    assert first["data"]["summary"]["probability"] == 0.7
    saved = store.get_artifact(first["data"]["id"])
    assert saved["task_id"] == ctx.task_id
    close_window(env)

    def forbidden(*args, **kwargs):
        raise AssertionError("Committed tool effects must recover without revalidation")

    monkeypatch.setattr("researchdesk.forecast_workflow.register_forecast", forbidden)
    assert registry.execute("register_forecast", values, ctx) == first
    store.cancel_case(case["id"])
    failed = registry.execute("register_forecast", values, ctx)
    assert not failed["ok"] and failed["error"]["code"] == "LEASE_LOST"


def test_concurrent_resolution_compare_and_swap_admits_exactly_one(env):
    _, research, case, _, _, _, _ = env
    forecast = register(env)
    close_window(env)
    args = resolution(evidence(env))
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait()
        try:
            return resolve_forecast(research, forecast["id"], args, key=f"concurrent-{index}")
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "RESOLUTION_CONFLICT" in results
    assert len(list_forecasts(research, case["id"])["items"][0]["resolutions"]) == 1


def test_api_auth_idempotency_readonly_and_resolution_contract(env):
    store, research, case, _, _, values, _ = env
    research.settings.operator_token = SecretStr("forecast-operator")
    app = create_app(research.settings, store, research)
    path = f"/api/cases/{case['id']}/forecasts"
    auth = {"Authorization": "Bearer forecast-operator", "Idempotency-Key": "operator-request-1"}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert (
            client.post(path, json=values, headers={"Idempotency-Key": "unauthorized"}).status_code
            == 401
        )
        assert (
            client.post(
                path, json=values, headers={"Authorization": auth["Authorization"]}
            ).status_code
            == 422
        )
        first = client.post(path, json=values, headers=auth)
        assert first.status_code == 201, first.text
        forecast = first.json()
        assert client.post(path, json=values, headers=auth).json() == forecast
        assert client.get(path, headers=auth).json()["items"][0]["forecast"] == forecast
        close_window(env)
        args = resolution(evidence(env))
        resolution_path = f"/api/forecasts/{forecast['id']}/resolutions"
        saved = client.post(resolution_path, json=args, headers=auth)
        assert saved.status_code == 201, saved.text
        assert saved.json()["content"]["resolver_origin"] == "operator_api"
        research.settings.read_only = True
        assert client.post(path, json=values, headers=auth).status_code == 403
        assert client.post(resolution_path, json=args, headers=auth).status_code == 403
        assert client.get(path, headers=auth).status_code == 200


def test_resolution_input_requires_evidence_even_for_unresolvable():
    with pytest.raises(ValidationError):
        ResolutionInput(outcome="unresolvable", rationale="No report was found", source_refs=[])


def test_synthetic_resolution_label_remains_visible_after_real_source_correction(env):
    store, research, case, _, _, values, _ = env
    real_source = evidence(env)
    real_hypothesis = store.put_artifact(
        case["id"],
        None,
        "hypothesis",
        "Ordinary hypothesis",
        {"source_artifact_ids": [real_source["id"]]},
    )
    forecast = register(
        env,
        hypothesis_id=real_hypothesis["id"],
        hypothesis_sha256=real_hypothesis["sha256"],
        source_artifact_ids=[real_source["id"]],
    )
    assert not forecast["content"]["synthetic"]
    close_window(env)
    invented = evidence(env, synthetic=True)
    first = resolve_forecast(research, forecast["id"], resolution(invented), key="synthetic-first")
    assert first["content"]["synthetic"]
    second = resolve_forecast(
        research,
        forecast["id"],
        resolution(real_source, previous_resolution_id=first["id"]),
        key="ordinary-correction",
    )
    assert second["content"]["synthetic"] and second["metadata"]["synthetic"]


def test_hypothesis_synthetic_lineage_propagates_without_direct_synthetic_source(env):
    real_source = evidence(env)
    forecast = register(env, source_artifact_ids=[real_source["id"]])
    assert forecast["content"]["synthetic"]


@pytest.mark.parametrize("role", ["coder", "reviewer"])
def test_actual_tool_execution_denies_other_roles(env, role):
    result = env[1].registry().execute("register_forecast", env[5], context(env, role))
    assert not result["ok"] and result["error"]["code"] == "forbidden_tool"


def test_worker_lease_loss_during_write_rolls_back_forecast(env, monkeypatch):
    store, research, case, _, _, values, _ = env
    ctx = context(env)
    emit = store._event

    def lose_lease(session, *args, **kwargs):
        result = emit(session, *args, **kwargs)
        session.execute(update(TaskRow).where(TaskRow.id == ctx.task_id).values(lease_until=0))
        return result

    monkeypatch.setattr(store, "_event", lose_lease)
    result = research.registry().execute("register_forecast", values, ctx)
    assert not result["ok"] and result["error"]["code"] == "LEASE_LOST"
    assert not store.list_forecast_artifacts(case["id"])


def test_corrupted_registration_source_is_rejected(env):
    store, _, _, source, _, _, _ = env
    with store.transaction() as session:
        session.execute(
            update(ArtifactRow)
            .where(ArtifactRow.id == source["id"])
            .values(content={"text": "Unhashed replacement"})
        )
    with pytest.raises(DomainError) as error:
        register(env)
    assert error.value.code == "ARTIFACT_CORRUPT"


def test_resolution_commit_rechecks_closed_window(env, monkeypatch):
    store, research, case, _, _, values, clock = env
    forecast = register(env)
    close_window(env)
    source = evidence(env)
    emit = store._event

    def clock_shift(session, *args, **kwargs):
        result = emit(session, *args, **kwargs)
        clock.instant = datetime.fromisoformat(values["closes_at"]) - timedelta(seconds=1)
        return result

    monkeypatch.setattr(store, "_event", clock_shift)
    with pytest.raises(DomainError) as error:
        resolve_forecast(research, forecast["id"], resolution(source), key="shifted-clock")
    assert error.value.code == "FORECAST_NOT_DUE"
    assert not list_forecasts(research, case["id"])["items"][0]["resolutions"]


def test_forecast_history_is_not_truncated_by_library_cap(env):
    store, research, case, *_ = env
    first = register(env)
    # Bulk seed valid immutable rows to exercise the actual >500 read boundary.
    with store.transaction() as session:
        session.add_all(
            ArtifactRow(
                id=f"forecast-history-{index}",
                case_id=case["id"],
                task_id=None,
                kind="forecast",
                title=first["title"],
                content=first["content"],
                sha256=first["sha256"],
                details=first["metadata"],
                request_hash="0" * 64,
            )
            for index in range(505)
        )
    items = list_forecasts(research, case["id"])["items"]
    assert len(items) == 506
    assert first["id"] in {item["forecast"]["id"] for item in items}


def test_agent_write_uses_one_transaction_with_in_memory_sqlite(env):
    # Nested read Sessions inside the write guard would rollback this connection.
    store = Store("sqlite://")
    try:
        research = ResearchTools(store, Settings(_env_file=None))
        case = store.create_case("In-memory case", "Forecast retained transaction test")
        source = store.put_artifact(case["id"], None, "evidence", "Source", "Test source")
        hypothesis = store.put_artifact(case["id"], None, "hypothesis", "Hypothesis", {})
        task = store.create_task(case["id"], "researcher", "Register a forecast")
        store.claim_task("memory-worker")
        ctx = ToolContext(
            store,
            case["id"],
            task["id"],
            "memory-call",
            "memory-worker",
            lambda: store.is_cancelled(task["id"]),
        )
        args = {
            **env[5],
            "hypothesis_id": hypothesis["id"],
            "hypothesis_sha256": hypothesis["sha256"],
            "source_artifact_ids": [source["id"]],
        }
        result = research.registry().execute("register_forecast", args, ctx)
        assert result["ok"], result
        assert store.get_artifact(result["data"]["id"])["kind"] == "forecast"
        assert len(store.list_forecast_artifacts(case["id"])) == 1
    finally:
        store.close()
