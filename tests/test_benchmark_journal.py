"""Independent synthetic journal tests: no model, network, or billable requests."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from researchdesk.agents.providers import ProviderError, ProviderTurn, ToolCall
from researchdesk.research.benchmark_journal import Journal, MeteredProvider, runner_lock

BINDING = {"bundle_sha256": "a" * 64, "split": "development"}
MESSAGES = [{"role": "user", "content": "Synthetic fixture question"}]
TOOLS = [{"type": "function", "name": "synthetic_read", "parameters": {"type": "object"}}]
INSTRUCTION = "Use only the synthetic source fixture."


def plan():
    manifest = SimpleNamespace(
        cases=[
            SimpleNamespace(case_id="synthetic-dev-A", split="development"),
            SimpleNamespace(case_id="../../synthetic-dev-B", split="development"),
            SimpleNamespace(case_id="synthetic-final", split="final"),
        ]
    )
    protocol = SimpleNamespace(
        repetitions=2, arms=("generalist", "fixed_specialists", "adaptive_specialists")
    )
    return manifest, protocol


def initialize(journal, *, binding=BINDING, split="development"):
    manifest, protocol = plan()
    journal.initialize(binding=binding, manifest=manifest, protocol=protocol, split=split)


@pytest.fixture
def journal(tmp_path):
    with runner_lock(tmp_path):
        instance = Journal(tmp_path)
        initialize(instance)
        try:
            yield instance
        finally:
            instance.close()


class SyntheticProvider:
    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome or ProviderTurn(
            text="Synthetic retained response",
            tool_calls=[ToolCall("synthetic-call", "synthetic_read", {"artifact_id": "fixture"})],
            usage={"input_tokens": 17, "output_tokens": 9},
            continuation={"provider": "synthetic", "response_id": "fixture-response"},
        )

    def complete(self, messages, tools, instruction, cancelled=lambda: False):
        self.calls.append({"messages": messages, "tools": tools, "instruction": instruction})
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def metered(journal, provider, *, attempt=None, task="synthetic-root", max_calls=3):
    wrapper = MeteredProvider(provider, journal, attempt or journal.attempts()[0]["id"], max_calls)
    wrapper.task_id = task
    return wrapper


def test_one_global_model_budget_covers_root_and_every_child_task(journal):
    provider = SyntheticProvider()
    attempt = journal.attempts()[0]["id"]
    first = metered(journal, provider, attempt=attempt, task="root", max_calls=2)
    first.complete(MESSAGES, TOOLS, INSTRUCTION)
    child = metered(journal, provider, attempt=attempt, task="child-1", max_calls=2)
    child.complete(MESSAGES, TOOLS, INSTRUCTION)
    another_child = metered(journal, provider, attempt=attempt, task="child-2", max_calls=2)
    with pytest.raises(ProviderError) as error:
        another_child.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert error.value.code == "benchmark_model_budget"
    assert len(provider.calls) == 2
    receipts = journal.model_calls(attempt)
    assert {row["task_id"] for row in receipts} == {"root", "child-1"}
    assert len(receipts) == 2
    # A different scheduled attempt receives its own predeclared envelope.
    other = metered(journal, provider, attempt=journal.attempts()[1]["id"], max_calls=2)
    other.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert len(provider.calls) == 3


def test_completed_turn_cache_survives_restart_without_spending_or_losing_tool_usage(tmp_path):
    first_provider = SyntheticProvider()
    with runner_lock(tmp_path):
        journal = Journal(tmp_path)
        initialize(journal)
        attempt_id = journal.attempts()[0]["id"]
        result = metered(journal, first_provider, attempt=attempt_id, max_calls=1).complete(
            MESSAGES, TOOLS, INSTRUCTION
        )
        saved = journal.model_calls(attempt_id)[0]
        assert saved["status"] == "completed" and saved["ended"] is not None
        journal.close()
    should_not_call = SyntheticProvider(AssertionError("A cached response must not spend again"))
    with runner_lock(tmp_path):
        journal = Journal(tmp_path)
        initialize(journal)
        try:
            restored = metered(journal, should_not_call, attempt=attempt_id, max_calls=1).complete(
                MESSAGES, TOOLS, INSTRUCTION
            )
            assert asdict(restored) == asdict(result)
            assert journal.model_calls(attempt_id) == [saved]
            assert not should_not_call.calls
            assert len(first_provider.calls) == 1
        finally:
            journal.close()


@pytest.mark.parametrize("changed", ["messages", "tools", "instruction"])
def test_same_turn_with_changed_request_cannot_reuse_cache_or_issue_paid_retry(journal, changed):
    provider = SyntheticProvider()
    wrapper = metered(journal, provider)
    wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    arguments = {"messages": MESSAGES, "tools": TOOLS, "instruction": INSTRUCTION}
    arguments[changed] = {
        "messages": [{"role": "user", "content": "Changed synthetic input"}],
        "tools": [],
        "instruction": "Changed instruction",
    }[changed]
    with pytest.raises(ProviderError) as error:
        wrapper.complete(**arguments)
    assert error.value.code == "benchmark_request_changed"
    assert len(provider.calls) == 1
    assert len(journal.model_calls(wrapper.attempt_id)) == 1


def test_next_assistant_turn_is_a_new_counted_request_not_a_duplicate(journal):
    provider = SyntheticProvider()
    wrapper = metered(journal, provider)
    first = wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    next_messages = [*MESSAGES, first.message(), {"role": "tool", "content": "Synthetic result"}]
    second = wrapper.complete(next_messages, TOOLS, INSTRUCTION)
    assert second == first
    assert [row["turn"] for row in journal.model_calls(wrapper.attempt_id)] == [0, 1]
    assert len(provider.calls) == 2


def test_inflight_ambiguous_crash_is_durable_and_never_retried_after_restart(tmp_path):
    interrupted = SyntheticProvider(KeyboardInterrupt("Synthetic process interruption"))
    with runner_lock(tmp_path):
        journal = Journal(tmp_path)
        initialize(journal)
        attempt_id = journal.attempts()[0]["id"]
        with pytest.raises(KeyboardInterrupt):
            metered(journal, interrupted, attempt=attempt_id).complete(MESSAGES, TOOLS, INSTRUCTION)
        receipt = journal.model_calls(attempt_id)[0]
        assert receipt["status"] == "inflight"
        assert receipt["response"] is None and receipt["ended"] is None
        journal.close()
    second_provider = SyntheticProvider()
    with runner_lock(tmp_path):
        resumed = Journal(tmp_path)
        try:
            with pytest.raises(ProviderError) as error:
                metered(resumed, second_provider, attempt=attempt_id).complete(
                    MESSAGES, TOOLS, INSTRUCTION
                )
            assert error.value.code == "benchmark_request_indeterminate"
            assert second_provider.calls == []
            assert len(interrupted.calls) == 1
            assert resumed.model_calls(attempt_id) == [receipt]
        finally:
            resumed.close()


@pytest.mark.parametrize(
    "failure,code",
    [
        (
            ProviderError("synthetic_provider_error", "PRIVATE source text"),
            "synthetic_provider_error",
        ),
        (RuntimeError("PRIVATE provider output"), "provider_failed"),
    ],
)
def test_failed_calls_are_retained_sanitized_counted_and_not_retried(journal, failure, code):
    provider = SyntheticProvider(failure)
    wrapper = metered(journal, provider, max_calls=1)
    with pytest.raises(ProviderError) as first:
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert first.value.code == code
    assert "PRIVATE" not in first.value.message
    receipt = journal.model_calls(wrapper.attempt_id)[0]
    assert receipt["status"] == "failed" and receipt["error_code"] == code
    assert receipt["ended"] is not None and receipt["response"] is None
    assert "PRIVATE" not in str(receipt)
    with pytest.raises(ProviderError) as again:
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert again.value.code == "benchmark_request_indeterminate"
    wrapper.task_id = "new-child"
    with pytest.raises(ProviderError) as budget:
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert budget.value.code == "benchmark_model_budget"
    assert len(provider.calls) == 1
    assert journal.model_calls(wrapper.attempt_id) == [receipt]


def test_response_encoding_failure_is_retained_instead_of_fabricating_a_success(journal):
    provider = SyntheticProvider(ProviderTurn(text="Synthetic", usage={"tokens": float("nan")}))
    wrapper = metered(journal, provider)
    with pytest.raises(ProviderError) as error:
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert error.value.code == "provider_failed"
    assert journal.model_calls(wrapper.attempt_id)[0]["status"] == "failed"
    with pytest.raises(ProviderError, match="will not be retried"):
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert len(provider.calls) == 1


def test_missing_task_and_pre_request_cancellation_do_not_spend_budget(journal):
    provider = SyntheticProvider()
    wrapper = metered(journal, provider)
    wrapper.task_id = None
    with pytest.raises(ProviderError) as missing:
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION)
    assert missing.value.code == "benchmark_task_missing"
    wrapper.task_id = "root"
    with pytest.raises(ProviderError) as cancelled:
        wrapper.complete(MESSAGES, TOOLS, INSTRUCTION, cancelled=lambda: True)
    assert cancelled.value.code == "cancelled"
    assert provider.calls == []
    assert journal.model_calls(wrapper.attempt_id) == []


def test_attempt_matrix_is_complete_deterministic_private_and_not_extended_on_resume(tmp_path):
    matrices = []
    for name in ("first", "second"):
        directory = tmp_path / name
        with runner_lock(directory):
            journal = Journal(directory)
            try:
                initialize(journal)
                planned = journal.attempts()
                initialize(journal)
                assert journal.attempts() == planned
                matrices.append(planned)
            finally:
                journal.close()
    assert matrices[0] == matrices[1]
    attempts = matrices[0]
    assert len(attempts) == 12  # Two development cases, three arms, two repetitions.
    assert {row["case_id"] for row in attempts} == {"synthetic-dev-A", "../../synthetic-dev-B"}
    assert {(row["arm"], row["repetition"]) for row in attempts} == {
        (arm, repeat) for arm in plan()[1].arms for repeat in range(2)
    }
    assert [row["ordinal"] for row in attempts] == list(range(12))
    assert len({row["id"] for row in attempts}) == 12
    assert all(
        len(row["id"]) == 64 and set(row["id"]) <= set("0123456789abcdef") for row in attempts
    )
    assert all(row["status"] == "planned" and row["result"] is None for row in attempts)


def test_changed_run_binding_is_rejected_without_mutating_existing_plan(journal):
    original = journal.attempts()
    with pytest.raises(ValueError, match="different benchmark run"):
        initialize(journal, binding={**BINDING, "bundle_sha256": "b" * 64})
    assert journal.attempts() == original


def test_empty_split_initialization_rolls_back_binding_and_allows_a_valid_plan(tmp_path):
    with runner_lock(tmp_path):
        journal = Journal(tmp_path)
        try:
            with pytest.raises(ValueError, match="no cases"):
                initialize(journal, split="missing-split")
            assert journal.attempts() == []
            assert journal.connection.execute("SELECT COUNT(*) FROM binding").fetchone()[0] == 0
            initialize(journal)
            assert len(journal.attempts()) == 12
        finally:
            journal.close()


@pytest.mark.parametrize("terminal", ["completed", "failed", "blocked"])
def test_terminal_attempt_result_and_first_start_time_are_immutable(journal, terminal):
    attempt = journal.attempts()[0]
    with pytest.raises(ValueError, match="Only running"):
        journal.finish(attempt["id"], terminal, {"not_started": True})
    assert journal.start(attempt["id"], now=100)["started"] == 100
    assert journal.start(attempt["id"], now=200)["started"] == 100
    journal.finish(attempt["id"], terminal, {"synthetic": True, "clinical_quality_score": None})
    final = next(row for row in journal.attempts() if row["id"] == attempt["id"])
    assert final["status"] == terminal and final["ended"] is not None
    assert journal.start(attempt["id"], now=300) == final
    with pytest.raises(ValueError, match="immutable final"):
        journal.finish(attempt["id"], terminal, {"replaced": True})
    assert next(row for row in journal.attempts() if row["id"] == attempt["id"]) == final
    with pytest.raises(ValueError, match="Unknown terminal"):
        journal.finish(attempt["id"], "running", {})


def test_preflight_records_remain_append_only_and_do_not_claim_attempt_completion(journal):
    journal.preflight({"configured": False, "reason": "Synthetic provider disabled"})
    journal.preflight({"configured": True, "environment": {"synthetic": True}})
    rows = journal.connection.execute("SELECT * FROM preflight ORDER BY id").fetchall()
    assert len(rows) == 2 and rows[0]["id"] < rows[1]["id"]
    assert "disabled" in rows[0]["result"]
    assert "environment" in rows[1]["result"]
    assert all(row["status"] == "planned" for row in journal.attempts())


def test_runner_lock_rejects_a_second_owner_and_releases_after_failure(tmp_path):
    with pytest.raises(RuntimeError, match="Synthetic interrupted owner"):
        with runner_lock(tmp_path):
            with pytest.raises(ValueError, match="Another benchmark runner"):
                with runner_lock(tmp_path):
                    pytest.fail("A second owner must not enter the lock")
            raise RuntimeError("Synthetic interrupted owner")
    with runner_lock(tmp_path):
        assert (tmp_path / ".runner.lock").is_file()
