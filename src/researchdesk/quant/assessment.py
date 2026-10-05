"""Deterministic diagnostics of recorded simulations, never an alpha approval.

No model judges another model's prose. The report checks the recorded accounting,
compares baselines, and states what this experiment cannot establish. It does not
estimate statistical significance without the required research/search history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

VERSION = "strategy-assessment.v1"
D = Decimal
TOLERANCE = D("0.00000001")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Missing or invalid numeric record")
    if len(str(value)) > 100:
        raise ValueError("Numeric record exceeds supported precision")
    number = D(str(value))
    if not number.is_finite() or abs(number) > D("1e30"):
        raise ValueError("Non-finite or out-of-range numeric record")
    if number and abs(number) < D("1e-30"):
        raise ValueError("Numeric record is below supported precision")
    return number


def _same(left, right):
    if abs(left - right) > TOLERANCE * max(D(1), abs(left), abs(right)):
        raise ValueError("Recorded metrics disagree with the retained equity curve")


def _period(result, *, start=None, end=None):
    metrics, points, trades = result["metrics"], result["equity_curve"], result["trades"]
    if not isinstance(points, list) or not 2 <= len(points) <= 100_000:
        raise ValueError("A period needs a bounded retained equity curve")
    if not isinstance(trades, list) or len(trades) > 100_000:
        raise ValueError("Invalid retained fill records")
    initial = _number(metrics["initial_cash"])
    if initial <= 0:
        raise ValueError("Initial capital must be positive")
    peak, drawdown, exposure = initial, D(0), []
    sessions = []
    for point in points:
        sessions.append(date.fromisoformat(point["session"]))
        equity, cash, quantity, mark = map(
            _number, (point["equity"], point["cash"], point["quantity"], point["mark"])
        )
        if equity <= 0 or cash < 0 or mark <= 0 or quantity < 0 or quantity != int(quantity):
            raise ValueError("Invalid long-only account observation")
        _same(equity, cash + quantity * mark)
        exposure.append(quantity * mark / equity)
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    if any(a >= b for a, b in zip(sessions, sessions[1:], strict=False)):
        raise ValueError("Evaluation sessions must be unique and chronological")
    if start and date.fromisoformat(start) != sessions[0]:
        raise ValueError("Evaluation start disagrees with retained observations")
    if end and date.fromisoformat(end) != sessions[-1]:
        raise ValueError("Evaluation end disagrees with retained observations")
    final = _number(points[-1]["equity"])
    net = final / initial - 1
    _same(final, _number(metrics["final_equity"]))
    _same(net, _number(metrics["net_return"]))
    _same(drawdown, _number(metrics["max_drawdown"]))
    if type(metrics["fill_count"]) is not int or metrics["fill_count"] != len(trades):
        raise ValueError("Recorded fill count disagrees with retained fills")
    fees = _number(metrics["fees"])
    fill_fees = [_number(t["fee"]) for t in trades]
    if fees < 0 or any(fee < 0 for fee in fill_fees):
        raise ValueError("Negative recorded fees")
    _same(fees, sum(fill_fees, D(0)))
    baseline = result.get("baseline", {})
    comparisons = {}
    for name in ("cash", "buy_hold"):
        if name not in baseline:
            continue
        values = baseline[name]
        baseline_return = _number(values["net_return"])
        if baseline_return < -1:
            raise ValueError("Invalid baseline return")
        _same(_number(values["final_equity"]), initial * (1 + baseline_return))
        comparisons[name] = {
            "net_return": str(baseline_return),
            "difference": str(net - baseline_return),
            "outperformed": net > baseline_return,
        }
    return {
        "start_session": sessions[0].isoformat(),
        "end_session": sessions[-1].isoformat(),
        "sessions": len(points),
        "return_observations": len(points) - 1,
        "initial_cash": str(initial),
        "final_equity": str(final),
        "net_return": str(net),
        "net_pnl": str(final - initial),
        "max_drawdown": str(drawdown),
        "fill_count": len(trades),
        "fees": str(fees),
        "invested_sessions": sum(value > 0 for value in exposure),
        "mean_close_exposure": str(sum(exposure) / len(exposure)),
        "max_close_exposure": str(max(exposure)),
        "baselines": comparisons,
        "buy_hold_allocation": baseline.get("buy_hold_spec", {}).get("allocation"),
    }


def assess_result(result: dict) -> dict:
    """Read frozen inputs only; a malformed result produces an explicit failure.

    Ordinary historical simulations and reset walk-forward folds are distinct.
    Exposure is the arithmetic mean of end-of-session invested fractions, not
    risk-adjusted alpha, duration-weighted exposure, or a matched-risk benchmark.
    """
    report = {
        "schema_version": VERSION,
        "status": "unavailable",
        "edge_status": "unestablished",
        "headline": "The recorded result cannot be assessed.",
        "basis": "historical_simulation",
        "profitability": "unknown",
        "periods": [],
        "checks": [],
        "limitations": [
            "Historical profit or baseline outperformance does not establish predictive edge.",
            "This report is deterministic evidence accounting, not a score of originality "
            "or a trading approval.",
        ],
    }
    try:
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise ValueError("A completed structured experiment is required")
        payload = {k: v for k, v in result.items() if k not in {"assessment", "result_sha256"}}
        report["simulation_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        spec, validation = result["spec"], result["validation"]
        folds = result.get("folds", [])
        if not isinstance(folds, list) or len(folds) > 1000:
            raise ValueError("Invalid fold records")
        with localcontext() as context:
            context.prec = 40
            if "walk_forward" in spec:
                if not folds:
                    raise ValueError("Walk-forward results require retained folds")
                report["basis"] = "reset_walk_forward_folds"
                periods, previous_end = [], None
                for fold in folds:
                    train_start, train_end, test_start, test_end = (
                        date.fromisoformat(fold[key])
                        for key in ("train_start", "train_end", "test_start", "test_end")
                    )
                    if not train_start <= train_end < test_start <= test_end:
                        raise ValueError("Training must precede each test fold")
                    if previous_end and test_start <= previous_end:
                        raise ValueError("Test folds overlap")
                    periods.append(_period(fold, start=fold["test_start"], end=fold["test_end"]))
                    previous_end = test_end
                cumulative = D(1)
                for period in periods:
                    cumulative *= 1 + D(period["net_return"])
                net = cumulative - 1
                _same(net, _number(result["metrics"]["geometrically_linked_fold_return"]))
                report["limitations"].append(
                    "Each fold resets capital. The linked fold return is not a continuous "
                    "portfolio return; no combined drawdown or Sharpe is inferred."
                )
            else:
                if folds:
                    raise ValueError("Undeclared fold evaluation")
                periods = [
                    _period(result, start=spec.get("start_session"), end=spec.get("end_session"))
                ]
                net = D(periods[0]["net_return"])
        synthetic = validation.get("synthetic_data")
        if type(synthetic) is not bool:
            raise ValueError("Dataset provenance is not classified as real or synthetic")
        execution = spec["execution"]
        fee, slippage = _number(execution["fee_bps"]), _number(execution["slippage_bps"])
        if min(fee, slippage) < 0:
            raise ValueError("Cost assumptions cannot be negative")
        report.update(
            status="assessed",
            periods=periods,
            net_return=str(net),
            synthetic_data=synthetic,
            profitability="positive" if net > 0 else "negative" if net < 0 else "flat",
            headline=(
                "The linked test folds gained value; investable edge is unestablished."
                if net > 0 and folds
                else "The linked test folds did not gain value; investable edge is unestablished."
                if folds
                else "This simulation made money; predictive edge is unestablished."
                if net > 0
                else "This simulation lost money."
                if net < 0
                else "This simulation finished flat."
            ),
            cost_assumptions={"fee_bps": str(fee), "slippage_bps": str(slippage)},
        )
        checks = report["checks"]

        def check(code, status, message):
            checks.append({"code": code, "status": status, "message": message})

        check(
            "accounting",
            "checked",
            "Reported return, drawdown, account values and fees reconcile to retained "
            "observations. This is not an independent fill-engine audit.",
        )
        check(
            "data",
            "limited" if synthetic else "recorded",
            "Synthetic prices: software verification only."
            if synthetic
            else "Recorded market observations; point-in-time source availability and "
            "selection bias are not verified here.",
        )
        if all({"cash", "buy_hold"} <= set(p["baselines"]) for p in periods):
            check(
                "baselines",
                "recorded",
                "Cash and buy-and-hold comparisons are recorded. Different market exposure "
                "prevents interpreting the return difference as alpha.",
            )
        else:
            check(
                "baselines",
                "missing",
                "A cash or buy-and-hold comparison is missing for at least one period.",
            )
        check(
            "costs",
            "assumed",
            f"Fees {fee} bps and slippage {slippage} bps are fixed assumptions; no cost "
            "sensitivity, spread/impact or capacity validation is supplied.",
        )
        check(
            "chronology",
            "recorded" if folds else "missing",
            "Training precedes nonoverlapping test folds. Repeated research on these folds "
            "can still bias selection."
            if folds
            else "No chronological train/test folds are recorded for this experiment.",
        )
        check(
            "holdout",
            "missing",
            "No protected final holdout or prospectively frozen strategy result is "
            "established by this experiment.",
        )
        check(
            "search_history",
            "missing",
            "No complete strategy/parameter search and researcher decision history is "
            "supplied to this assessment; selection-adjusted significance cannot be calculated.",
        )
        check(
            "robustness",
            "missing",
            "No cross-period, cross-instrument, parameter-neighborhood or independent "
            "replication evidence is supplied to this assessment.",
        )
        check(
            "mechanism",
            "not_assessed",
            "A causal economic mechanism and information advantage require evidence beyond "
            "a trading rule or polished agent explanation.",
        )
        check(
            "prospective",
            "missing",
            "No prospective after-cost paper outcome is established by this historical experiment.",
        )
    except (
        KeyError,
        TypeError,
        AttributeError,
        ValueError,
        InvalidOperation,
        OverflowError,
    ) as exc:
        report.update(status="unavailable", periods=[], profitability="unknown")
        report["checks"] = [
            {"code": "invalid_record", "status": "failed", "message": str(exc)[:400]}
        ]
    return report


def assessed_result(result: dict) -> dict:
    """Persist report and simulation atomically in the same experiment artifact."""
    result = {k: v for k, v in result.items() if k not in {"assessment", "result_sha256"}}
    result["assessment"] = assess_result(result)
    result["result_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result


def assess_saved_experiment(store, experiment_id: str) -> dict:
    """Versioned, idempotent annotation of an immutable older experiment."""
    from researchdesk.errors import DomainError

    experiment = store.get_artifact(experiment_id)
    if experiment["kind"] != "experiment":
        raise DomainError("ARTIFACT_TYPE", "Assessment requires an experiment.")
    reference = {key: experiment[key] for key in ("id", "kind", "title", "sha256")}
    report = {**assess_result(experiment["content"]), "experiment": reference}
    return store.put_artifact(
        experiment["case_id"],
        None,
        "strategy_assessment",
        f"Strategy assessment · {experiment['title']}"[:200],
        report,
        {"inputs": [reference], "method": VERSION, "execution_eligible": False},
        idempotency_key=f"{VERSION}:{experiment_id}:{experiment['sha256']}",
    )
