"""Run pinned, full-engine LEAN scenarios on generated data with no external network.

Build the launcher with lean/ResearchDeskOptionsAlgorithm.cs first. Observations
are retained even when a native model fails an economic/admission expectation.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from lean_fixture import build_fixture

LEAN_COMMIT = "705b9551be1aaa821c7f77896a7eb8fcd07b92ee"
CASES = (
    ("native_itm", "native_itm"),
    ("market_itm", "market_itm"),
    ("market_itm_replay", "market_itm"),
    ("market_otm", "market_otm"),
    ("market_shortfall", "market_shortfall"),
    ("market_quote_only", "market_quote_only"),
    ("market_stale_trade", "market_stale_trade"),
    ("vertical_assignment", "vertical_assignment"),
)
MINUTE_CASES = (
    ("minute_itm", "minute_itm"),
    ("minute_itm_replay", "minute_itm"),
    ("minute_otm", "minute_otm"),
)
MINUTE_FIRST_BAR_END = datetime(2026, 1, 16, 20, 56, tzinfo=UTC)


def observed_time(value, *, local=False):
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        if not local:
            raise ValueError("UTC observation timestamp must include its time zone.")
        timestamp = timestamp.replace(tzinfo=ZoneInfo("America/New_York"))
    return timestamp.astimezone(UTC)


def minute_chronology(observed):
    """Check delivered bar chronology independently of native portfolio completion."""
    errors = []
    bar_ends = []
    receipt_times = []
    entry_times = []
    previous_slice_time = None
    try:
        for snapshot in observed["observed_slices"]:
            slice_time = observed_time(snapshot["utc_time"])
            if previous_slice_time is not None and slice_time < previous_slice_time:
                errors.append("Observed slice receipt times are out of chronological order.")
            previous_slice_time = slice_time
            for bar in snapshot["quote_bars"]:
                start = observed_time(bar["time"], local=True)
                end = observed_time(bar["end_time"], local=True)
                received = observed_time(bar["receipt_utc_time"])
                if (end - start).total_seconds() != 60 or bar["period_seconds"] != 60:
                    errors.append("Observed quote bar does not cover exactly one minute.")
                if end > received or end > slice_time:
                    errors.append("Observed quote bar ends after its receipt or slice time.")
                if received != slice_time:
                    errors.append("Quote bar receipt time differs from its enclosing slice.")
                if bar["instrument"] == "call100":
                    bar_ends.append(end)
                    receipt_times.append(received)
        if not bar_ends or bar_ends[0] != MINUTE_FIRST_BAR_END:
            errors.append("First observed call100 bar must end at 2026-01-16T20:56:00Z.")
        for event in observed["order_events"]:
            if (
                event["instrument"] == "call100"
                and event["order_type"] == "Market"
                and Decimal(str(event["fill_quantity"])) != 0
            ):
                filled = observed_time(event["utc_time"])
                entry_times.append(filled)
                if filled < MINUTE_FIRST_BAR_END or (receipt_times and filled < receipt_times[0]):
                    errors.append(
                        "Entry filled before the first completed call100 bar was received."
                    )
        if not entry_times:
            errors.append("No actual market entry fill is available to qualify chronology.")
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as exc:
        errors.append(f"Cannot qualify minute chronology: {exc}")
    return {
        "qualified": not errors,
        "first_allowed_entry_utc": MINUTE_FIRST_BAR_END.isoformat(),
        "observed_call100_bar_count": len(bar_ends),
        "first_observed_bar_end_utc": bar_ends[0].isoformat() if bar_ends else None,
        "first_entry_fill_utc": min(entry_times).isoformat() if entry_times else None,
        "errors": errors,
    }


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def config(binary_dir, data_dir, case_dir, scenario):
    return {
        "environment": "backtesting",
        "algorithm-type-name": "ResearchDeskOptionsAlgorithm",
        "algorithm-language": "CSharp",
        "algorithm-location": str(binary_dir / "QuantConnect.Algorithm.CSharp.dll"),
        "composer-dll-directory": str(binary_dir),
        "data-folder": str(data_dir),
        "results-destination-folder": str(case_dir / "engine-results"),
        "object-store-root": str(case_dir / "object-store"),
        "algorithm-id": "researchdesk-" + scenario,
        "backtest-name": "Synthetic options comparison: " + scenario,
        "close-automatically": True,
        "debugging": False,
        "live-mode": False,
        "force-exchange-always-open": False,
        "show-missing-data-logs": True,
        "job-user-id": "0",
        "api-access-token": "",
        "job-organization-id": "",
        "log-handler": "QuantConnect.Logging.CompositeLogHandler",
        "messaging-handler": "QuantConnect.Messaging.Messaging",
        "job-queue-handler": "QuantConnect.Queues.JobQueue",
        "api-handler": "QuantConnect.Api.Api",
        "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
        "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
        "data-channel-provider": "DataChannelProvider",
        "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore",
        "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
        "symbol-tick-limit": 10,
        "symbol-minute-limit": 10,
        "symbol-second-limit": 10,
        "maximum-data-points-per-chart-series": 1000,
        "parameters": {"scenario": scenario, "receipt-path": str(case_dir / "observed.json")},
        "environments": {
            "backtesting": {
                "live-mode": False,
                "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
                "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
                "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
                "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
                "history-provider": [
                    "QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"
                ],
                "transaction-handler": (
                    "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler"
                ),
            }
        },
    }


def economic_state(state):
    if not state:
        return None
    return {
        key: state[key] for key in ("cash", "unsettled_cash", "total_portfolio_value", "total_fees")
    } | {"quantities": {key: holding["quantity"] for key, holding in state["holdings"].items()}}


def final_engine_states(case_dir, scenario):
    """Read final native result files; callback status precedes engine completion."""
    states = []
    for name in (f"researchdesk-{scenario}-summary.json", f"researchdesk-{scenario}.json"):
        path = case_dir / "engine-results" / name
        if not path.is_file():
            continue
        record = {"file": path.name, "sha256": file_hash(path), "state": {}}
        try:
            payload = json.loads(path.read_text())
            state = payload.get("state") if isinstance(payload, dict) else None
            if not isinstance(state, dict):
                raise ValueError("Native result has no state object.")
            record["state"] = state
        except (OSError, ValueError) as exc:
            record["error"] = str(exc)
        states.append(record)
    return states


def assess(observed, *, terminal_verified=False):
    """Report the predeclared oracle separately from whatever the engine actually did."""
    scenario = observed["scenario"]
    events = observed["order_events"]
    fills = [event for event in events if Decimal(str(event["fill_quantity"])) != 0]
    state = observed.get("end_state") or observed.get("last_state")
    result = {
        "scenario": scenario,
        "entry_submitted": observed["entry_submitted"],
        "on_end_of_algorithm_called": observed["on_end_of_algorithm_called"],
        "algorithm_status_in_callback": observed["algorithm_status"],
        "fill_events": [
            {
                key: event[key]
                for key in (
                    "order_id",
                    "event_id",
                    "utc_time",
                    "instrument",
                    "order_type",
                    "status",
                    "fill_quantity",
                    "fill_price",
                    "fee",
                    "is_assignment",
                )
            }
            for event in fills
        ],
        "last_callback_economics": economic_state(state),
        "terminal_economics": (
            economic_state(observed.get("end_state")) if terminal_verified else None
        ),
        "terminal_verified": terminal_verified,
        "engine_adoption": False,
    }
    if scenario == "native_itm":
        result["partial_fill_observed"] = any(e["status"] == "PartiallyFilled" for e in events)
        result["remainder_cancellation_requested"] = observed["cancel_requested"]
        result["required_original_tape_result"] = {
            "cash": 9800,
            "call100": 0,
            "underlying": 100,
            "exactly_one_contract_filled_and_remainder_cancelled": True,
        }
    elif scenario in {"market_itm", "market_otm", "minute_itm", "minute_otm"}:
        itm = scenario in {"market_itm", "minute_itm"}
        expected = {"cash": 9800 if itm else 19800, "call100": 0, "underlying": 100 if itm else 0}
        result["expected_after_one_entry_at_2_and_native_expiry"] = expected
        entry_fills = [
            event
            for event in fills
            if event["instrument"] == "call100" and event["order_type"] == "Market"
        ]
        result["entry_fill_matches_control"] = (
            sum(Decimal(str(event["fill_quantity"])) for event in entry_fills) == 1
            and all(Decimal(str(event["fill_price"])) == 2 for event in entry_fills)
            and all(Decimal(str(event["fee"])) == 0 for event in entry_fills)
        )
        if scenario.startswith("minute_"):
            result["minute_chronology"] = minute_chronology(observed)
            result["original_tick_partial_fill_qualified"] = False
        result["matches_terminal_accounting"] = (
            None
            if not terminal_verified
            else (
                result["entry_fill_matches_control"]
                and result.get("minute_chronology", {"qualified": True})["qualified"]
                and bool(state)
                and Decimal(str(state["total_fees"])) == 0
                and (
                    Decimal(str(state["cash"])) + Decimal(str(state["unsettled_cash"]))
                    == expected["cash"]
                    and state["holdings"]["call100"]["quantity"] == expected["call100"]
                    and state["holdings"]["underlying"]["quantity"] == expected["underlying"]
                )
            )
        )
    elif scenario == "market_shortfall":
        result["exercise_funding_deficit_after_entry_at_2"] = 200
        result["negative_cash_observed"] = any(Decimal(str(e["state"]["cash"])) < 0 for e in events)
        result["policy"] = "A cash-only mandate cannot admit borrowing or partially failed state."
    elif scenario in {"market_quote_only", "market_stale_trade"}:
        result["fresh_last_trade_policy_admission"] = False
        result["policy"] = (
            "No qualified current last trade. Preserve native quote/trade selection as observed."
        )
    elif scenario == "vertical_assignment":
        assignment_orders = list(
            dict.fromkeys(
                e["order_id"] for e in events if e["is_assignment"] and e["fill_quantity"] != 0
            )
        )
        result["assignment_order_ids"] = assignment_orders
        result["expected_after_entry"] = {
            "cash": 20880,
            "call120": 1,
            "call100": -1,
            "underlying": 0,
        }
        result["expected_after_short_assignment"] = {
            "cash": 30880,
            "call120": 1,
            "call100": 0,
            "underlying": -100,
        }
        if assignment_orders:
            # Select by first assignment identity, never by desirable portfolio balances.
            first = [e for e in events if e["order_id"] == assignment_orders[0]]
            result["first_assignment_event_batch"] = first
            result["first_assignment_last_callback_state"] = economic_state(first[-1]["state"])
        result["policy"] = (
            "Callback state can be intermediate. Reconcile the full first assignment batch "
            "and later slices; cash proceeds coexist with a short-stock obligation."
        )
    return result


def observe_case(case_dir, scenario, returncode, *, timed_out=False):
    """Classify native completion without treating a partial callback as a final book."""
    entry = {"returncode": returncode, "timed_out": timed_out}
    errors = []
    states = []
    try:
        states = final_engine_states(case_dir, scenario)
    except (OSError, ValueError) as exc:
        errors.append(f"Cannot read native final results: {exc}")
    entry["native_engine_states"] = states
    errors.extend(
        f"Cannot read native result {record['file']}: {record['error']}"
        for record in states
        if "error" in record
    )
    native_error = any(
        record["state"].get("Status") == "RuntimeError" or bool(record["state"].get("RuntimeError"))
        for record in states
    )
    native_completed = bool(states) and all(
        record["state"].get("Status") == "Completed"
        and bool(record["state"].get("EndTime"))
        and record["state"].get("RuntimeError") == ""
        for record in states
    )
    if timed_out:
        status = "timed_out"
    elif native_error:
        status = "runtime_error"
    elif returncode != 0:
        status = "process_error"
    elif native_completed:
        status = "completed"
    else:
        status = "incomplete"
    entry["engine_execution_status"] = status
    if status in {"timed_out", "process_error", "incomplete"}:
        errors.append(f"Native engine execution is {status}.")

    receipt = case_dir / "observed.json"
    if receipt.is_file():
        entry["receipt_sha256"] = file_hash(receipt)
        try:
            observed = json.loads(receipt.read_text())
            if (
                observed["lean_commit"] != LEAN_COMMIT
                or observed["scenario"] != scenario
                or observed["schema_version"] != 1
            ):
                raise ValueError("Receipt identity/schema does not match this run.")
            # An intent flag is set before submitting an order. Require an actual
            # recorded submission or native order event too, including rejections.
            entry_reached = bool(observed["entry_submitted"]) and bool(
                observed["submitted_orders"] or observed["order_events"]
            )
            if not entry_reached:
                errors.append("The native input/order path never reached entry submission.")
            if scenario in {"minute_itm", "minute_otm"}:
                errors.extend(minute_chronology(observed)["errors"])
            terminal_verified = (
                status == "completed"
                and not errors
                and observed["on_end_of_algorithm_called"] is True
                and bool(observed.get("end_state"))
            )
            if status == "completed" and not terminal_verified:
                errors.append("Completed native run lacks a complete terminal observation.")
            entry["assessment"] = assess(observed, terminal_verified=terminal_verified)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as exc:
            errors.append(f"Cannot assess algorithm receipt: {exc}")
    else:
        errors.append("Engine produced no algorithm observation receipt.")
    if errors:
        entry["errors"] = errors
    return entry


def run(lean_root, output, *, suite="ticks"):
    if suite not in {"ticks", "minute"}:
        raise ValueError(f"Unknown experiment suite: {suite}")
    cases = CASES if suite == "ticks" else MINUTE_CASES
    lean_root, output = lean_root.resolve(), output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(
            "Output must be a new directory; existing observations are never replaced."
        )
    # The CI command creates a dedicated network namespace before invoking this script.
    interfaces = sorted(
        line.split(":", 1)[0].strip()
        for line in Path("/proc/self/net/dev").read_text().splitlines()[2:]
        if ":" in line
    )
    if interfaces != ["lo"]:
        raise RuntimeError("Run inside an isolated network namespace with only loopback.")
    actual_commit = subprocess.check_output(
        ["git", "-c", f"safe.directory={lean_root}", "-C", str(lean_root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    if actual_commit != LEAN_COMMIT:
        raise ValueError(f"Unexpected LEAN source revision: {actual_commit}")
    binary_dir = lean_root / "Launcher/bin/Release"
    launcher = binary_dir / "QuantConnect.Lean.Launcher.dll"
    dotnet = shutil.which("dotnet")
    if not launcher.is_file() or not dotnet:
        raise ValueError("Build the pinned launcher first and make dotnet available.")
    output.mkdir(parents=True)
    summary = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "suite": suite,
        "lean_commit": actual_commit,
        "launcher_sha256": file_hash(launcher),
        "algorithm_sha256": file_hash(binary_dir / "QuantConnect.Algorithm.CSharp.dll"),
        "network_interfaces": interfaces,
        "engine_adoption": False,
        "harness_status": "incomplete",
        "cases": [],
    }
    try:
        for run_name, scenario in cases:
            case_dir = output / run_name
            case_dir.mkdir()
            manifest = build_fixture(scenario, case_dir / "data", lean_root / "Data")
            write_json(case_dir / "fixture.json", manifest)
            write_json(
                case_dir / "config.json", config(binary_dir, case_dir / "data", case_dir, scenario)
            )
            environment = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": str(case_dir),
                "LANG": "C.UTF-8",
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_NOLOGO": "1",
            }
            if "DOTNET_ROOT" in os.environ:
                environment["DOTNET_ROOT"] = os.environ["DOTNET_ROOT"]
            started = time.monotonic()
            returncode = None
            timed_out = False
            launch_error = None
            with (case_dir / "engine.log").open("w", encoding="utf-8") as log:
                try:
                    process = subprocess.run(
                        [dotnet, str(launcher), "--config", str(case_dir / "config.json")],
                        cwd=binary_dir,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=180,
                        check=False,
                    )
                    returncode = process.returncode
                except subprocess.TimeoutExpired:
                    # subprocess.run kills and waits for its child on timeout.
                    timed_out = True
                except OSError as exc:
                    launch_error = str(exc)
            entry = {
                "run": run_name,
                "scenario": scenario,
                **observe_case(case_dir, scenario, returncode, timed_out=timed_out),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "fixture_sha256": file_hash(case_dir / "fixture.json"),
                "config_sha256": file_hash(case_dir / "config.json"),
                "engine_log_sha256": file_hash(case_dir / "engine.log"),
            }
            if launch_error:
                entry.setdefault("errors", []).append(f"Unable to launch engine: {launch_error}")
            if entry.get("errors") or entry["engine_execution_status"] != "completed":
                entry["log_tail"] = (case_dir / "engine.log").read_text()[-8000:]
            summary["cases"].append(entry)
            write_json(output / "summary.json", summary)
            print(json.dumps(entry), flush=True)
        if any(case.get("errors") for case in summary["cases"]):
            summary["harness_status"] = "failed"
        elif any(case["engine_execution_status"] == "runtime_error" for case in summary["cases"]):
            summary["harness_status"] = "observed_with_engine_errors"
        else:
            summary["harness_status"] = "observed"
        by_name = {case["run"]: case for case in summary["cases"]}
        funded_name = "market_itm" if suite == "ticks" else "minute_itm"
        funded = by_name.get(funded_name, {}).get("assessment", {})
        replay = by_name.get(funded_name + "_replay", {}).get("assessment", {})
        summary["funded_replay_terminal_comparison_available"] = bool(
            funded.get("terminal_verified") and replay.get("terminal_verified")
        )
        summary["funded_replay_economic_state_equal"] = None
        if summary["funded_replay_terminal_comparison_available"]:
            summary["funded_replay_economic_state_equal"] = (
                funded["terminal_economics"] == replay["terminal_economics"]
            )
        if summary["harness_status"] == "failed":
            raise RuntimeError("Scenario matrix finished with incomplete or invalid observations.")
    finally:
        write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=("ticks", "minute"), default="ticks")
    args = parser.parse_args()
    run(args.lean_root, args.output, suite=args.suite)


if __name__ == "__main__":
    main()
