"""Verify failure classification without pretending to execute the native engine."""

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    directory = ROOT / "examples/engine_spikes"
    spec = importlib.util.spec_from_file_location("lean_runner", directory / "run_lean_spike.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(directory))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


runner = load_runner()


def receipt(scenario="market_itm", *, ended=True):
    state = {
        "cash": 9800,
        "unsettled_cash": 0,
        "total_portfolio_value": 20800,
        "total_fees": 0,
        "holdings": {"call100": {"quantity": 0}, "underlying": {"quantity": 100}},
    }
    if scenario in {"market_otm", "minute_otm"}:
        state.update(cash=19800, total_portfolio_value=19800)
        state["holdings"]["underlying"]["quantity"] = 0
    event = {
        "order_id": 1,
        "event_id": 1,
        "utc_time": "2026-01-16T20:59:56Z",
        "instrument": "call100",
        "order_type": "Market",
        "status": "Filled",
        "fill_quantity": 1,
        "fill_price": 2,
        "fee": 0,
        "is_assignment": False,
        "state": deepcopy(state),
    }
    payload = {
        "lean_commit": runner.LEAN_COMMIT,
        "schema_version": 1,
        "scenario": scenario,
        "entry_submitted": True,
        "submitted_orders": [{"order_id": 1}],
        "on_end_of_algorithm_called": ended,
        "algorithm_status": "Running",
        "cancel_requested": False,
        "order_events": [event],
        "last_state": state,
        "end_state": deepcopy(state) if ended else None,
    }
    if scenario.startswith("minute_"):
        event["utc_time"] = "2026-01-16T20:56:00Z"
        payload["observed_slices"] = [
            {
                "utc_time": f"2026-01-16T20:{minute + 1}:00Z",
                "quote_bars": [
                    {
                        "instrument": "call100",
                        "time": f"2026-01-16T15:{minute}:00.0000000",
                        "end_time": f"2026-01-16T15:{minute + 1}:00.0000000",
                        "period_seconds": 60,
                        "receipt_utc_time": f"2026-01-16T20:{minute + 1}:00Z",
                        "bid": dict.fromkeys(("open", "high", "low", "close"), 2),
                        "ask": dict.fromkeys(("open", "high", "low", "close"), 2),
                        "bid_size": 10,
                        "ask_size": 10,
                    }
                ],
            }
            for minute in (55, 56)
        ]
    return payload


def native_state(**changes):
    return {
        "Status": "Completed",
        "EndTime": "2026-10-05T15:00:00",
        "RuntimeError": "",
        "StackTrace": "",
        **changes,
    }


def write_native(case_dir, scenario, state, *, summary=True):
    directory = case_dir / "engine-results"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = "-summary" if summary else ""
    path = directory / f"researchdesk-{scenario}{suffix}.json"
    path.write_text(json.dumps({"state": state}))
    return path


@pytest.mark.parametrize("summary", [True, False])
def test_native_completion_reads_exact_summary_or_full_result(tmp_path, summary):
    write_native(tmp_path, "market_itm", native_state(), summary=summary)
    # Unrelated outputs, including malformed ones, must not influence this case.
    (tmp_path / "engine-results/unrelated.json").write_text("not json")
    write_native(tmp_path, "market_otm", native_state(Status="RuntimeError"))
    (tmp_path / "observed.json").write_text(json.dumps(receipt()))
    observed = runner.observe_case(tmp_path, "market_itm", 0)
    assert len(observed["native_engine_states"]) == 1
    assert observed["engine_execution_status"] == "completed"
    assert observed["assessment"]["terminal_verified"] is True
    assert observed["assessment"]["matches_terminal_accounting"] is True
    assert observed["assessment"]["algorithm_status_in_callback"] == "Running"


@pytest.mark.parametrize(
    "change",
    ["missing_status", "missing_end", "runtime_error", "nonzero", "no_callback", "no_end_state"],
)
def test_each_completion_requirement_prevents_partial_terminal_qualification(tmp_path, change):
    payload = receipt()
    state = native_state()
    code = 0
    if change == "missing_status":
        del state["Status"]
    elif change == "missing_end":
        state["EndTime"] = ""
    elif change == "runtime_error":
        state["RuntimeError"] = "Exercise could not complete."
    elif change == "nonzero":
        code = 137
    elif change == "no_callback":
        payload["on_end_of_algorithm_called"] = False
    else:
        payload["end_state"] = None
    write_native(tmp_path, "market_itm", state)
    (tmp_path / "observed.json").write_text(json.dumps(payload))
    observed = runner.observe_case(tmp_path, "market_itm", code)
    assessment = observed["assessment"]
    assert assessment["last_callback_economics"]["cash"] == 9800
    assert assessment["terminal_verified"] is False
    assert assessment["terminal_economics"] is None
    assert assessment["matches_terminal_accounting"] is None


def test_conflicting_or_corrupt_native_results_cannot_qualify(tmp_path):
    write_native(tmp_path, "market_itm", native_state())
    full = write_native(tmp_path, "market_itm", native_state(Status="Running"), summary=False)
    (tmp_path / "observed.json").write_text(json.dumps(receipt()))
    observed = runner.observe_case(tmp_path, "market_itm", 0)
    assert observed["engine_execution_status"] == "incomplete"
    assert len(observed["native_engine_states"]) == 2
    full.write_text("{invalid")
    observed = runner.observe_case(tmp_path, "market_itm", 0)
    assert observed["errors"]
    assert len(observed["native_engine_states"]) == 2
    assert "error" in observed["native_engine_states"][1]
    assert observed["assessment"]["terminal_economics"] is None


@pytest.mark.parametrize("intent", [False, True])
def test_absent_actual_submission_is_not_a_success(tmp_path, intent):
    payload = receipt()
    payload.update(entry_submitted=intent, submitted_orders=[], order_events=[])
    write_native(tmp_path, "market_itm", native_state())
    (tmp_path / "observed.json").write_text(json.dumps(payload))
    observed = runner.observe_case(tmp_path, "market_itm", 0)
    assert any("never reached entry submission" in error for error in observed["errors"])
    assert observed["assessment"]["terminal_economics"] is None


def test_matching_balances_without_correct_entry_fills_do_not_pass_accounting(tmp_path):
    payload = receipt()
    payload["order_events"][0]["fill_price"] = 3
    write_native(tmp_path, "market_itm", native_state())
    (tmp_path / "observed.json").write_text(json.dumps(payload))
    assessment = runner.observe_case(tmp_path, "market_itm", 0)["assessment"]
    assert assessment["terminal_verified"] is True
    assert assessment["entry_fill_matches_control"] is False
    assert assessment["matches_terminal_accounting"] is False


@pytest.mark.parametrize("scenario", ["minute_itm", "minute_otm"])
def test_minute_controls_qualify_completed_bars_and_conditional_accounting(tmp_path, scenario):
    write_native(tmp_path, scenario, native_state())
    (tmp_path / "observed.json").write_text(json.dumps(receipt(scenario)))
    observed = runner.observe_case(tmp_path, scenario, 0)
    assert "errors" not in observed
    assessment = observed["assessment"]
    assert assessment["terminal_verified"] is True
    assert assessment["matches_terminal_accounting"] is True
    assert assessment["minute_chronology"]["qualified"] is True
    assert assessment["minute_chronology"]["observed_call100_bar_count"] == 2
    assert assessment["original_tick_partial_fill_qualified"] is False


@pytest.mark.parametrize(
    "change",
    [
        "early_fill",
        "future_bar",
        "receipt_before_end",
        "wrong_period",
        "wrong_first_bar",
        "missing_bars",
        "missing_fill",
        "naive_utc",
        "reversed_slices",
    ],
)
def test_minute_chronology_cannot_qualify_invalid_or_missing_observations(tmp_path, change):
    scenario = "minute_itm"
    payload = receipt(scenario)
    first = payload["observed_slices"][0]
    last = payload["observed_slices"][1]
    if change == "early_fill":
        payload["order_events"][0]["utc_time"] = "2026-01-16T20:55:59Z"
    elif change == "future_bar":
        # The first bar and entry are sound; every later bar must be checked too.
        last["quote_bars"][0].update(time="2026-01-16T15:57:00", end_time="2026-01-16T15:58:00")
    elif change == "receipt_before_end":
        first["quote_bars"][0]["receipt_utc_time"] = "2026-01-16T20:55:59Z"
    elif change == "wrong_period":
        first["quote_bars"][0]["period_seconds"] = 1
    elif change == "wrong_first_bar":
        first["quote_bars"][0].update(time="2026-01-16T15:54:00", end_time="2026-01-16T15:55:00")
    elif change == "missing_bars":
        payload["observed_slices"] = []
    elif change == "missing_fill":
        payload["order_events"] = []
    elif change == "reversed_slices":
        payload["observed_slices"].reverse()
    else:
        first["utc_time"] = "2026-01-16T20:56:00"
    write_native(tmp_path, scenario, native_state())
    (tmp_path / "observed.json").write_text(json.dumps(payload))
    observed = runner.observe_case(tmp_path, scenario, 0)
    assert observed["engine_execution_status"] == "completed"
    assert observed["errors"]
    assessment = observed["assessment"]
    assert assessment["minute_chronology"]["qualified"] is False
    assert assessment["terminal_verified"] is False
    assert assessment["terminal_economics"] is None
    assert assessment["last_callback_economics"]["cash"] == 9800
    assert assessment["matches_terminal_accounting"] is None


@pytest.mark.parametrize("field,value", [("fill_quantity", 2), ("fill_price", 3), ("fee", 1)])
def test_minute_matching_balances_still_require_exact_entry(tmp_path, field, value):
    payload = receipt("minute_itm")
    payload["order_events"][0][field] = value
    write_native(tmp_path, "minute_itm", native_state())
    (tmp_path / "observed.json").write_text(json.dumps(payload))
    assessment = runner.observe_case(tmp_path, "minute_itm", 0)["assessment"]
    assert assessment["minute_chronology"]["qualified"] is True
    assert assessment["terminal_verified"] is True
    assert assessment["entry_fill_matches_control"] is False
    assert assessment["matches_terminal_accounting"] is False


@pytest.fixture
def matrix(tmp_path, monkeypatch):
    lean = tmp_path / "Lean"
    binary = lean / "Launcher/bin/Release"
    binary.mkdir(parents=True)
    for name in ("QuantConnect.Lean.Launcher.dll", "QuantConnect.Algorithm.CSharp.dll"):
        (binary / name).write_bytes(b"test placeholder, not an executable")
    for name in (
        "market-hours/market-hours-database.json",
        "symbol-properties/symbol-properties-database.csv",
    ):
        path = lean / "Data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test static metadata")
    original_read = Path.read_text

    def read_text(path, *args, **kwargs):
        if str(path) == "/proc/self/net/dev":
            return "header\nheader\nlo: 0\n"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/test/dotnet")
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *args, **kwargs: runner.LEAN_COMMIT
    )
    calls = []

    def execute(cases, *, suite="ticks"):
        monkeypatch.setattr(
            runner,
            "CASES" if suite == "ticks" else "MINUTE_CASES",
            tuple((name, scenario) for name, scenario, _ in cases),
        )
        actions = {name: action for name, _, action in cases}

        def engine(command, **kwargs):
            case_dir = Path(command[-1]).parent
            configuration = json.loads(Path(command[-1]).read_text())
            scenario = configuration["parameters"]["scenario"]
            action = actions[case_dir.name]
            calls.append(case_dir.name)
            kwargs["stdout"].write(f"Synthetic test process: {action}\n")
            payload = receipt(scenario, ended=action not in {"timeout", "partial", "runtime_error"})
            code = 0
            if action == "runtime_error":
                state = native_state(Status="RuntimeError", RuntimeError="Negative exercise cash.")
                code = 1
            elif action == "partial":
                state = native_state(Status="Running", EndTime="")
            else:
                state = native_state()
            if action == "different":
                payload["end_state"]["cash"] = 9801
            elif action == "wrong_identity":
                payload["scenario"] = "wrong"
            (case_dir / "observed.json").write_text(
                "{bad json" if action == "malformed" else json.dumps(payload)
            )
            if action == "timeout":
                raise subprocess.TimeoutExpired(command, 180)
            write_native(case_dir, scenario, state)
            return SimpleNamespace(returncode=code)

        monkeypatch.setattr(runner.subprocess, "run", engine)
        output = tmp_path / "results"
        return lean, output, calls

    return execute


def test_timeouts_and_bad_receipts_are_retained_and_remaining_cases_run(matrix):
    lean, output, calls = matrix(
        [
            ("bad_json", "native_itm", "malformed"),
            ("timed_out", "market_itm", "timeout"),
            ("wrong_identity", "market_itm", "wrong_identity"),
            ("good", "market_otm", "complete"),
        ]
    )
    with pytest.raises(RuntimeError, match="matrix finished"):
        runner.run(lean, output)
    assert calls == ["bad_json", "timed_out", "wrong_identity", "good"]
    summary = json.loads((output / "summary.json").read_text())
    assert summary["harness_status"] == "failed"
    assert summary["suite"] == "ticks"
    assert len(summary["cases"]) == 4
    for case in summary["cases"][:3]:
        assert case["errors"] and case["receipt_sha256"] and case["engine_log_sha256"]
        assert (output / case["run"] / "observed.json").exists()
    timeout = summary["cases"][1]
    assert timeout["engine_execution_status"] == "timed_out"
    assert timeout["returncode"] is None
    assert timeout["assessment"]["last_callback_economics"]
    assert timeout["assessment"]["terminal_economics"] is None
    assert summary["cases"][-1]["assessment"]["matches_terminal_accounting"] is True


def test_native_shortfall_error_is_preserved_as_an_engine_error_outcome(matrix):
    lean, output, calls = matrix(
        [
            ("market_shortfall", "market_shortfall", "runtime_error"),
            ("market_otm", "market_otm", "complete"),
        ]
    )
    summary = runner.run(lean, output)
    assert calls == ["market_shortfall", "market_otm"]
    assert summary["harness_status"] == "observed_with_engine_errors"
    failed_engine = summary["cases"][0]
    assert failed_engine["returncode"] == 1
    assert failed_engine["engine_execution_status"] == "runtime_error"
    assert failed_engine["native_engine_states"][0]["state"]["RuntimeError"]
    assert failed_engine["assessment"]["terminal_verified"] is False


@pytest.mark.parametrize(
    "actions,expected",
    [
        (("complete", "complete"), True),
        (("complete", "different"), False),
        (("complete", "partial"), None),
        (("partial", "partial"), None),
    ],
)
@pytest.mark.parametrize("suite", ["ticks", "minute"])
def test_replay_compares_only_verified_terminal_states(matrix, actions, expected, suite):
    name = "market_itm" if suite == "ticks" else "minute_itm"
    lean, output, _ = matrix(
        [
            (name, name, actions[0]),
            (name + "_replay", name, actions[1]),
        ],
        suite=suite,
    )
    if "partial" in actions:
        with pytest.raises(RuntimeError):
            runner.run(lean, output, suite=suite)
    else:
        runner.run(lean, output, suite=suite)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["funded_replay_terminal_comparison_available"] is (expected is not None)
    assert summary["funded_replay_economic_state_equal"] is expected


def test_explicit_minute_suite_runs_separate_cases_and_replay(matrix):
    cases = [
        ("minute_itm", "minute_itm", "complete"),
        ("minute_itm_replay", "minute_itm", "complete"),
        ("minute_otm", "minute_otm", "complete"),
    ]
    lean, output, calls = matrix(cases, suite="minute")
    summary = runner.run(lean, output, suite="minute")
    assert summary["suite"] == "minute"
    assert calls == [name for name, _, _ in cases]
    assert summary["funded_replay_terminal_comparison_available"] is True
    assert summary["funded_replay_economic_state_equal"] is True
    assert all(case["assessment"]["matches_terminal_accounting"] for case in summary["cases"])


@pytest.mark.parametrize("arguments,expected", [([], "ticks"), (["--suite", "minute"], "minute")])
def test_cli_selects_suite_explicitly_and_preserves_tick_default(monkeypatch, arguments, expected):
    calls = []
    monkeypatch.setattr(
        sys, "argv", ["run_lean_spike.py", "--lean-root", "Lean", "--output", "results", *arguments]
    )
    monkeypatch.setattr(runner, "run", lambda *args, **kwargs: calls.append(kwargs["suite"]))
    runner.main()
    assert calls == [expected]
