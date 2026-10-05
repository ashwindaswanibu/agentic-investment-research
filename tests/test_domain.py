"""Domain gates with explicit synthetic engineering fixtures, never market results."""

import hashlib
import json
from datetime import date, timedelta

import pytest

from researchdesk.agents import ToolContext
from researchdesk.agents.registry import ToolError
from researchdesk.config import Settings
from researchdesk.domain import (
    MAX_TOOL_RESULT_CHARS,
    ArtifactWrite,
    ExperimentInput,
    ProposalInput,
    ResearchTools,
    ReviewInput,
    artifact_ref,
)
from researchdesk.errors import DomainError
from researchdesk.quant import MarketSnapshot, StrategySpec
from researchdesk.sandbox import SandboxResult
from researchdesk.store import Store


@pytest.fixture
def environment(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'domain.db'}")
    settings = Settings(_env_file=None)
    case = store.create_case("Domain fixture", "Test validation gates, not investment performance")
    tools = ResearchTools(store, settings)
    yield store, case, tools
    store.close()


def context(store, case, role, call_id="fixture-call"):
    existing = store.list_tasks(case["id"])
    task = store.create_task(
        case["id"],
        role,
        "Bounded engineering test task",
        parent_id=existing[0]["id"] if existing else None,
    )
    claimed = store.claim_task("fixture-worker")
    assert claimed["id"] == task["id"]
    return ToolContext(store, case["id"], task["id"], call_id, "fixture-worker", lambda: False)


def dataset(store, case, offset=0):
    bars = []
    for index, value in enumerate([10, 11, 10, 12, 11]):
        value += offset
        bars.append(
            {
                "session": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
                "open": str(value),
                "high": str(value),
                "low": str(value),
                "close": str(value),
                "volume": 10000,
            }
        )
    snapshot = MarketSnapshot.model_validate(
        {
            "symbol": "TEST",
            "source": "Synthetic engineering fixture",
            "retrieved_at": "2025-01-01T00:00:00Z",
            "price_basis": "raw_no_corporate_actions",
            "bars": bars,
            "synthetic": True,
        }
    )
    return store.put_artifact(
        case["id"], None, "dataset", "Synthetic test fixture", snapshot.model_dump(mode="json")
    )


def experiment(environment):
    store, case, tools = environment
    data = dataset(store, case)
    coder = context(store, case, "coder")
    result = tools.experiment(
        coder, ExperimentInput(dataset_id=data["id"], strategy=StrategySpec(kind="buy_hold"))
    )
    return coder, data, result


def review_arguments(target, **changes):
    values = dict(
        artifact_id=target["id"],
        artifact_sha256=target["sha256"],
        verdict="accept",
        findings="Engineering fixture review checks exact input binding and limitations.",
        experiment_ids=[target["id"]],
    )
    values.update(changes)
    return ReviewInput(**values)


def test_same_task_cannot_review_its_own_output(environment):
    coder, _, target = experiment(environment)
    with pytest.raises(ToolError) as error:
        environment[2].review(coder, review_arguments(target))
    assert error.value.code == "independent_review_required"


def test_review_cannot_bind_wrong_artifact_version(environment):
    store, case, tools = environment
    _, _, target = experiment(environment)
    reviewer = context(store, case, "reviewer")
    with pytest.raises(ToolError) as error:
        tools.review(reviewer, review_arguments(target, artifact_sha256="0" * 64))
    assert error.value.code == "review_hash_mismatch"
    assert not store.list_artifacts(case["id"], kind="review")


def test_review_rejects_unrelated_experiment(environment):
    store, case, tools = environment
    _, _, target = experiment(environment)
    other_case = store.create_case("Other fixture", "Unrelated evidence")
    unrelated = store.put_artifact(other_case["id"], None, "experiment", "Unrelated", {})
    reviewer = context(store, case, "reviewer")
    with pytest.raises(DomainError) as error:
        tools.review(reviewer, review_arguments(target, experiment_ids=[unrelated["id"]]))
    assert error.value.code == "ARTIFACT_CASE"


def test_review_of_code_requires_experiment_of_that_exact_code(environment):
    store, case, tools = environment
    coder, _, target = experiment(environment)
    code = store.put_artifact(
        case["id"],
        coder.task_id,
        "code",
        "Different code",
        "def run(payload): return {'target_weight': 0}",
    )
    reviewer = context(store, case, "reviewer")
    with pytest.raises(ToolError) as error:
        tools.review(reviewer, review_arguments(code, experiment_ids=[target["id"]]))
    assert error.value.code == "unrelated_experiment"


def test_accepted_synthetic_experiment_still_cannot_authorize_paper_order(environment):
    store, case, tools = environment
    _, _, target = experiment(environment)
    reviewer = context(store, case, "reviewer")
    review = tools.review(reviewer, review_arguments(target))
    assert review["metadata"]["inputs"][0] == artifact_ref(target)
    with pytest.raises(DomainError) as error:
        tools.validate_decision(target["id"], review["id"])
    assert error.value.code == "INELIGIBLE_EXPERIMENT"


def test_rejected_review_never_authorizes_a_decision(environment):
    store, case, tools = environment
    _, _, target = experiment(environment)
    reviewer = context(store, case, "reviewer")
    review = tools.review(reviewer, review_arguments(target, verdict="reject"))
    with pytest.raises(DomainError) as error:
        tools.validate_decision(target["id"], review["id"])
    assert error.value.code == "REVIEW_REQUIRED"


def test_registry_prevents_role_and_artifact_kind_forgery(environment):
    store, case, tools = environment
    researcher = context(store, case, "researcher")
    registry = tools.registry()
    write = registry.execute(
        "write_artifact",
        {"kind": "experiment", "title": "Fabricated", "content": "Pretend this code was evaluated"},
        researcher,
    )
    assert not write["ok"] and write["error"]["code"] == "invalid_arguments"
    code = registry.execute(
        "write_artifact",
        {"kind": "code", "title": "Wrong role", "content": "def run(payload): return 1"},
        researcher,
    )
    assert not code["ok"] and code["error"]["code"] == "forbidden_artifact"
    review = registry.execute("review_artifact", {}, researcher)
    assert not review["ok"] and review["error"]["code"] == "forbidden_tool"
    assert not store.list_artifacts(case["id"])


def test_generated_strategy_container_receives_only_increasing_history_prefixes(environment):
    store, case, tools = environment
    data = dataset(store, case)
    coder = context(store, case, "coder", "experiment")
    source = "def run(payload): return {'target_weight': 0}"
    code = store.put_artifact(case["id"], coder.task_id, "code", "Fixture strategy", source)
    observed = []

    class RecordingSandbox:
        """Test fixture observes the orchestration boundary without executing Python."""

        def run(self, code, payload, **kwargs):
            assert code == source
            observed.append(payload)
            return SandboxResult(True, {"target_weight": 0})

    tools.sandbox = RecordingSandbox()
    result = tools.experiment(
        coder, ExperimentInput(dataset_id=data["id"], mode="generated_strategy", code_id=code["id"])
    )
    assert result["content"]["assessment"]["status"] == "assessed"
    assert result["content"]["assessment"]["edge_status"] == "unestablished"
    assert (
        store.get_artifact(result["id"])["content"]["assessment"] == result["content"]["assessment"]
    )
    assert [len(item["history"]) for item in observed] == [1, 2, 3, 4]
    assert all("artifacts" not in item and "future" not in item for item in observed)
    assert result["metadata"]["inputs"] == [artifact_ref(data), artifact_ref(code)]
    assert result["content"]["status"] == "completed"


def test_failed_generated_execution_does_not_create_completed_experiment(environment):
    store, case, tools = environment
    data = dataset(store, case)
    coder = context(store, case, "coder")
    code = tools.write(
        coder,
        ArtifactWrite(kind="code", title="Fixture strategy", content="def run(payload): return 0"),
    )

    class UnavailableSandbox:
        """Explicit unavailable-isolation fixture."""

        def run(self, *args, **kwargs):
            return SandboxResult(
                False, error={"code": "sandbox_unavailable", "message": "Test fixture"}
            )

    tools.sandbox = UnavailableSandbox()
    with pytest.raises(ToolError) as error:
        tools.experiment(
            coder,
            ExperimentInput(dataset_id=data["id"], mode="generated_strategy", code_id=code["id"]),
        )
    assert error.value.code == "strategy_execution_failed"
    assert not store.list_artifacts(case["id"], kind="experiment")


def test_proposal_must_match_evaluated_symbol_even_with_valid_gate(environment, monkeypatch):
    store, case, tools = environment
    _, _, target = experiment(environment)
    coordinator = context(store, case, "coordinator")
    # Isolate the symbol check; the preceding review/synthetic gates have separate tests.
    monkeypatch.setattr(tools, "validate_decision", lambda *a, **k: (target, target))
    with pytest.raises(ToolError) as error:
        tools.proposal(
            coordinator,
            ProposalInput(
                artifact_id=target["id"],
                review_id=target["id"],
                rationale="Test mismatched instruments cannot inherit an accepted experiment.",
                symbol="OTHER",
                side="buy",
                quantity=1,
                limit_price="10",
            ),
        )
    assert error.value.code == "decision_symbol"


@pytest.mark.parametrize("content", ["Synthetic document. " * 9000, {"fixture": "😀\x00" * 20000}])
def test_artifact_pages_reconstruct_original_without_unbounded_results(environment, content):
    store, case, tools = environment
    artifact = store.put_artifact(case["id"], None, "note", "Large synthetic fixture", content)
    reader = context(store, case, "researcher")
    registry = tools.registry()
    arguments = {"artifact_id": artifact["id"], "limit": 16000}
    pages = []
    while arguments is not None:
        result = registry.execute("read_artifact", arguments, reader)
        assert result["ok"], result
        assert len(json.dumps(result["data"])) <= MAX_TOOL_RESULT_CHARS
        page = result["data"]
        assert page["id"] == artifact["id"]
        assert page["sha256"] == artifact["sha256"]
        assert page["kind"] == "note"
        assert page["offset"] == sum(map(len, pages))
        assert 0 < page["returned_chars"] <= 16000
        assert page["returned_chars"] == len(page["text"])
        pages.append(page["text"])
        arguments = page["next_read"]["arguments"] if page["next_read"] else None
    joined = "".join(pages)
    assert (joined if isinstance(content, str) else json.loads(joined)) == content
    assert len(joined) == page["total_chars"]
    assert page["truncated"] is False and page["next_offset"] is None
    assert store.get_artifact(artifact["id"])["content"] == content


@pytest.mark.parametrize(
    "fields",
    [
        {"limit": 0},
        {"limit": 16001},
        {"limit": True},
        {"offset": -1},
        {"offset": 0.5},
        {"offset": True},
        {"section": "unknown"},
    ],
)
def test_artifact_read_rejects_invalid_page_arguments(environment, fields):
    store, case, tools = environment
    artifact = store.put_artifact(case["id"], None, "note", "Fixture", "short content")
    reader = context(store, case, "researcher")
    result = tools.registry().execute(
        "read_artifact", {"artifact_id": artifact["id"], **fields}, reader
    )
    assert not result["ok"] and result["error"]["code"] == "invalid_arguments"


def test_artifact_read_default_bound_and_out_of_range_offset(environment):
    store, case, tools = environment
    artifact = store.put_artifact(case["id"], None, "note", "Fixture", "x" * 20000)
    reader = context(store, case, "researcher")
    registry = tools.registry()
    result = registry.execute("read_artifact", {"artifact_id": artifact["id"]}, reader)
    assert result["ok"] and result["data"]["returned_chars"] == 12000
    result = registry.execute(
        "read_artifact", {"artifact_id": artifact["id"], "offset": 20001}, reader
    )
    assert not result["ok"] and result["error"]["code"] == "artifact_offset"


def test_large_metadata_remains_available_through_bounded_pagination(environment):
    store, case, tools = environment
    metadata = {"source": "Synthetic provenance fixture", "details": "source detail " * 8000}
    artifact = store.put_artifact(case["id"], None, "note", "Fixture", "short", metadata)
    reader = context(store, case, "researcher")
    registry = tools.registry()
    first = registry.execute("read_artifact", {"artifact_id": artifact["id"]}, reader)["data"]
    assert first["metadata"]["omitted"] is True
    hint = first["read_metadata"]
    pages = []
    while hint:
        result = registry.execute(hint["tool"], hint["arguments"], reader)
        assert result["ok"]
        assert len(json.dumps(result["data"])) <= MAX_TOOL_RESULT_CHARS
        pages.append(result["data"]["text"])
        hint = result["data"]["next_read"]
    assert json.loads("".join(pages)) == metadata


def test_library_tool_bounds_passages_without_changing_full_api_result(environment):
    store, case, tools = environment
    tools.settings.retrieval_mode = "lexical"
    source = "Synthetic glioblastoma evidence; never use as clinical evidence. " * 3000
    for index in range(20):
        store.put_artifact(
            case["id"],
            None,
            "evidence",
            f"Fixture {index}",
            {
                "text": source,
                "source": "Engineering fixture",
                "untrusted_source": True,
            },
        )
    reader = context(store, case, "researcher")
    api_result = tools.search("glioblastoma", limit=20)
    assert api_result["items"][0]["content"]["text"] == source
    result = tools.registry().execute(
        "search_library", {"query": "glioblastoma", "limit": 20}, reader
    )
    assert result["ok"]
    result = result["data"]
    assert len(json.dumps(result)) <= MAX_TOOL_RESULT_CHARS
    assert result["truncated"] is True
    assert result["items"] and result["model"] == "BM25"
    for item in result["items"]:
        assert "content" not in item
        assert item["provenance"]["source"] == "Engineering fixture"
        original = store.get_artifact(item["id"])
        assert item["sha256"] == original["sha256"]
        for passage in item["passages"]:
            page = tools.registry().execute(
                "read_artifact",
                {
                    "artifact_id": item["id"],
                    "offset": passage["start_char"],
                    "limit": passage["end_char"] - passage["start_char"],
                },
                reader,
            )["data"]
            assert page["text"] == passage["text"]


def test_unicode_heavy_search_hit_still_exposes_a_valid_reference(environment):
    store, case, tools = environment
    tools.settings.retrieval_mode = "lexical"
    content = ("glioblastoma " + "😀" * 300) * 30
    artifact = store.put_artifact(case["id"], None, "note", "Unicode fixture", content)
    reader = context(store, case, "researcher")
    result = tools.registry().execute("search_library", {"query": "glioblastoma"}, reader)
    assert result["ok"] and len(json.dumps(result["data"])) <= MAX_TOOL_RESULT_CHARS
    hit = result["data"]["items"][0]
    assert hit["id"] == artifact["id"]
    passage = hit["passages"][0]
    assert passage["excerpt_truncated"]
    assert content[passage["start_char"] : passage["end_char"]] == passage["text"]
    assert hashlib.sha256(passage["text"].encode()).hexdigest() == passage["text_sha256"]
    source = content[passage["start_char"] : passage["source_end_char"]]
    assert hashlib.sha256(source.encode()).hexdigest() == passage["source_chunk_sha256"]


def test_artifact_receipts_are_compact_and_still_support_exact_hash_review(environment):
    store, case, tools = environment
    data = dataset(store, case)
    coder = context(store, case, "coder")
    registry = tools.registry()
    produced = registry.execute("run_experiment", {"dataset_id": data["id"]}, coder)
    assert produced["ok"]
    receipt = produced["data"]
    assert "content" not in receipt and receipt["content_included"] is False
    assert receipt["metadata"]["inputs"] == [artifact_ref(data)]
    assert receipt["summary"]["status"] == "completed"
    assert receipt["summary"]["metrics"]
    reviewer = context(store, case, "reviewer")
    read = receipt["read"]
    inspected = registry.execute(read["tool"], read["arguments"], reviewer)["data"]
    assert json.loads(inspected["text"]) == store.get_artifact(receipt["id"])["content"]
    reviewed = registry.execute("review_artifact", review_arguments(receipt).model_dump(), reviewer)
    assert reviewed["ok"]
    review_receipt = reviewed["data"]
    assert "content" not in review_receipt
    saved_review = store.get_artifact(review_receipt["id"])
    assert saved_review["content"]["artifact_sha256"] == receipt["sha256"]
    assert saved_review["metadata"]["inputs"][0] == artifact_ref(receipt)


def test_large_written_code_returns_receipt_not_echoed_source(environment):
    store, case, tools = environment
    coder = context(store, case, "coder")
    content = "# Explicit synthetic code fixture\n" * 2500
    result = tools.registry().execute(
        "write_artifact",
        {
            "kind": "code",
            "title": "Large fixture",
            "content": content,
        },
        coder,
    )
    assert result["ok"]
    assert len(json.dumps(result["data"])) < 3000
    assert "content" not in result["data"]
    assert store.get_artifact(result["data"]["id"])["content"] == content


def test_get_clinical_trial_retains_record_and_provenance_without_inline_payload(
    environment, monkeypatch
):
    from researchdesk.data import clinical

    store, case, tools = environment
    fixture = {
        "id": "NCT00000001",
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "record": {"synthetic_fixture": "Study metadata " * 15000},
        "sha256": "a" * 64,
        "provenance": {
            "retrieved_at": "2025-01-01T00:00:00Z",
            "sha256": "b" * 64,
            "url": "https://clinicaltrials.gov/api/v2/studies/NCT00000001?format=json",
        },
        "untrusted_source": True,
    }
    calls = []

    def get_trial(identifier):
        calls.append(identifier)
        return fixture

    monkeypatch.setattr(clinical, "get_trial", get_trial)
    researcher = context(store, case, "researcher")
    registry = tools.registry()
    result = registry.execute("get_clinical_trial", {"nct_id": "NCT00000001"}, researcher)
    assert result["ok"] and calls == ["NCT00000001"]
    receipt = result["data"]
    assert receipt["kind"] == "evidence" and "content" not in receipt
    assert len(json.dumps(receipt)) < 4000
    assert receipt["provenance"]["provenance"] == fixture["provenance"]
    stored = store.get_artifact(receipt["id"])
    assert stored["content"] == fixture
    assert stored["metadata"]["provenance"] == fixture["provenance"]
    bad = registry.execute("get_clinical_trial", {"nct_id": "NCT123"}, researcher)
    assert not bad["ok"] and bad["error"]["code"] == "invalid_arguments"
    assert calls == ["NCT00000001"]


@pytest.mark.sandbox
def test_real_generated_python_matches_known_buy_and_hold_policy(environment):
    store, case, tools = environment
    if not tools.sandbox.availability()["available"]:
        pytest.skip("Docker daemon and built sandbox image required")
    data = dataset(store, case)
    coder = context(store, case, "coder", "generated-experiment")
    code = store.put_artifact(
        case["id"],
        coder.task_id,
        "code",
        "Fixture allocation policy",
        "def run(payload):\n"
        "    weight = '0.5' if len(payload['history']) == 1 else None\n"
        "    return {'target_weight': weight}",
    )
    generated = tools.experiment(
        coder, ExperimentInput(dataset_id=data["id"], mode="generated_strategy", code_id=code["id"])
    )
    other = ToolContext(
        store, case["id"], coder.task_id, "builtin-experiment", coder.worker_id, lambda: False
    )
    builtin = tools.experiment(
        other,
        ExperimentInput(
            dataset_id=data["id"], strategy=StrategySpec(kind="buy_hold", allocation="0.5")
        ),
    )
    assert generated["content"]["trades"] == builtin["content"]["trades"]
    assert generated["content"]["equity_curve"] == builtin["content"]["equity_curve"]
    assert generated["metadata"]["execution_eligible"] is False
