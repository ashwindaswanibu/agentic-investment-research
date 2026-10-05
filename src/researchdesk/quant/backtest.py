"""Causal daily simulation for one long-only equity/ETF and a cash account.

Signals consume a completed session and fill at the NEXT observed session open.
Dividends, borrow, leverage, options and intraday order paths are not simulated.
Generated Python must be invoked by the caller in a fresh, prefix-only sandbox;
this module never executes generated source or trusts a precomputed target vector.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from .models import BacktestSpec, Bar, MarketSnapshot, QuantError, StrategySpec, WalkForwardSpec

D = Decimal


@dataclass(frozen=True)
class HistoryContext:
    symbol: str
    bars: tuple[Bar, ...]
    cash: Decimal
    quantity: int
    parameters: dict

    def as_payload(self) -> dict:
        return {
            "symbol": self.symbol,
            "history": [bar.model_dump(mode="json") for bar in self.bars],
            "cash": str(self.cash),
            "quantity": self.quantity,
            "parameters": self.parameters,
        }


# None retains the existing position; a number requests a target NAV weight.
Policy = Callable[[HistoryContext], Decimal | float | str | None]


def _builtin(spec: StrategySpec) -> Policy:
    has_entered = False

    def policy(ctx: HistoryContext) -> Decimal | None:
        nonlocal has_entered
        if spec.kind == "cash":
            return D(0)
        if spec.kind == "buy_hold":
            if has_entered:
                return None
            has_entered = True
            return spec.allocation
        if len(ctx.bars) < spec.lookback:
            return D(0)
        average = sum(bar.close for bar in ctx.bars[-spec.lookback :]) / spec.lookback
        return spec.allocation if ctx.bars[-1].close > average else D(0)

    return policy


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _metrics(
    points: list[dict],
    initial: Decimal,
    total_fees: Decimal,
    turnover: Decimal,
    annual_sessions: int,
) -> dict:
    values = [initial, *(D(point["equity"]) for point in points)]
    peak = initial
    drawdown = D(0)
    returns = []
    for before, value in zip(values, values[1:], strict=False):
        if before <= 0:
            raise QuantError("invalid_nav", "NAV must remain positive for return calculation")
        returns.append(float(value / before - 1))
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak)
    # Initial no-fill point is an observation, not a fabricated prehistory return.
    returns = returns[1:]
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = (
        sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    )
    sharpe = mean / math.sqrt(variance) * math.sqrt(annual_sessions) if variance > 0 else None
    return {
        "initial_cash": str(initial),
        "final_equity": str(values[-1]),
        "net_return": str(values[-1] / initial - 1),
        "max_drawdown": str(drawdown),
        "fees": str(total_fees),
        "turnover_notional": str(turnover),
        "sharpe": sharpe,
        "sharpe_observations": len(returns),
        "sharpe_assumption": f"{annual_sessions} equally spaced sessions/year; zero cash yield",
    }


def run_backtest(
    snapshot: MarketSnapshot | dict,
    strategy: StrategySpec | dict | None = None,
    spec: BacktestSpec | dict | None = None,
    *,
    policy: Policy | None = None,
    policy_id: str | None = None,
    parameters: dict | None = None,
    _start: int = 0,
    _end: int | None = None,
    include_baseline: bool = True,
) -> dict:
    """Run real computations; a failing policy invalidates the experiment.

    A supplied policy receives immutable history through the decision session only.
    For untrusted/generated code the adapter MUST isolate each invocation and send
    only `HistoryContext.as_payload()`. Never mount the whole snapshot there.
    """
    snapshot = MarketSnapshot.model_validate(snapshot)
    strategy = StrategySpec.model_validate(strategy or {})
    spec = BacktestSpec.model_validate(spec or {})
    if policy is None and strategy.allocation > spec.max_allocation:
        raise QuantError("allocation_exceeded", "strategy allocation exceeds the experiment limit")
    if policy is not None and not policy_id:
        raise QuantError(
            "missing_policy_identity", "external policies require their code artifact hash"
        )
    execute_policy = policy or _builtin(strategy)
    end = len(snapshot.bars) if _end is None else _end
    if not 0 <= _start < end <= len(snapshot.bars) or end - _start < 2:
        raise QuantError("insufficient_sessions", "evaluation requires at least two sessions")
    if not snapshot.synthetic and not snapshot.corporate_actions_checked:
        raise QuantError(
            "unchecked_corporate_actions",
            "real datasets require an explicit corporate-action check",
        )
    if any(
        snapshot.bars[_start].session <= action.session <= snapshot.bars[end - 1].session
        for action in snapshot.corporate_actions
    ):
        raise QuantError(
            "unsupported_corporate_action",
            "dividends and splits within the evaluation interval are not supported",
        )
    cash, basis, qty = spec.initial_cash, D(0), 0
    pending: tuple[Decimal, str] | None = None
    trades, decisions, points = [], [], []
    fees = turnover = realized = D(0)
    fee_rate, slip_rate = spec.fee_bps / 10000, spec.slippage_bps / 10000
    for index in range(_start, end):
        bar = snapshot.bars[index]
        if pending is not None:
            weight, decision_session = pending
            nav_open = cash + qty * bar.open
            desired = weight * nav_open
            delta_value = desired - qty * bar.open
            side = "buy" if delta_value > 0 else "sell"
            price = bar.open * (1 + slip_rate if side == "buy" else 1 - slip_rate)
            if side == "buy":
                amount = max(
                    0,
                    min(
                        _floor(delta_value / (price * (1 + fee_rate))),
                        _floor(cash / (price * (1 + fee_rate))),
                    ),
                )
                # NAV drops by costs. Respect the resulting weight, not merely the order's size.
                while amount and (qty + amount) * bar.open > spec.max_allocation * (
                    nav_open - amount * (price * (1 + fee_rate) - bar.open)
                ):
                    amount -= 1
            else:
                amount = qty if weight == 0 else min(qty, max(0, _floor(-delta_value / bar.open)))
            if amount:
                fee = amount * price * fee_rate
                if side == "buy":
                    cost = amount * price + fee
                    cash -= cost
                    basis += cost
                    qty += amount
                    trade_realized = D(0)
                else:
                    allocated_basis = basis * amount / qty
                    proceeds = amount * price - fee
                    trade_realized = proceeds - allocated_basis
                    realized += trade_realized
                    cash += proceeds
                    basis -= allocated_basis
                    qty -= amount
                if cash < 0 or qty < 0:
                    raise QuantError("accounting_invariant", "cash or quantity became negative")
                fees += fee
                turnover += amount * price
                trades.append(
                    {
                        "decision_session": decision_session,
                        "session": bar.session.isoformat(),
                        "side": side,
                        "quantity": amount,
                        "price": str(price),
                        "fee": str(fee),
                        "cash_after": str(cash),
                        "realized_pnl": str(trade_realized),
                    }
                )
        pending = None
        equity = cash + qty * bar.close
        points.append(
            {
                "session": bar.session.isoformat(),
                "cash": str(cash),
                "quantity": qty,
                "mark": str(bar.close),
                "equity": str(equity),
            }
        )
        # Last-bar decisions would have no executable observation and are not solicited.
        if index + 1 < end:
            ctx = HistoryContext(
                snapshot.symbol, snapshot.bars[: index + 1], cash, qty, parameters or {}
            )
            raw = execute_policy(ctx)
            if isinstance(raw, bool):
                raise QuantError("invalid_policy_output", "target weight must be numeric or null")
            try:
                target = None if raw is None else D(str(raw))
            except Exception as exc:
                raise QuantError(
                    "invalid_policy_output", "target weight must be numeric or null"
                ) from exc
            if target is not None and (
                not target.is_finite() or not 0 <= target <= spec.max_allocation
            ):
                raise QuantError("invalid_policy_output", "target weight exceeds the allowed range")
            decisions.append(
                {
                    "session": bar.session.isoformat(),
                    "target_weight": str(target) if target is not None else None,
                    "history_sessions": index + 1,
                }
            )
            if target is not None:
                pending = (target, bar.session.isoformat())
    metrics = _metrics(points, spec.initial_cash, fees, turnover, spec.annual_sessions)
    metrics.update(
        {
            "realized_pnl": str(realized),
            "unrealized_pnl": str(qty * snapshot.bars[end - 1].close - basis),
            "fill_count": len(trades),
        }
    )
    result = {
        "status": "completed",
        "spec": {
            "dataset_sha256": snapshot.content_hash,
            "strategy": {
                "kind": "generated",
                "code_sha256": policy_id,
                "parameters": parameters or {},
            }
            if policy is not None
            else strategy.model_dump(mode="json"),
            "execution": spec.model_dump(mode="json"),
            "start_session": snapshot.bars[_start].session.isoformat(),
            "end_session": snapshot.bars[end - 1].session.isoformat(),
        },
        "metrics": metrics,
        "equity_curve": points,
        "folds": [],
        "trades": trades,
        "decisions": decisions,
        "validation": {
            "synthetic_data": snapshot.synthetic,
            "source": snapshot.source,
            "execution_timing": "next_observed_session_open",
            "integer_shares": True,
            "price_basis": snapshot.price_basis,
            "corporate_actions_checked": snapshot.corporate_actions_checked,
            "limitations": [
                "Single long-only equity/ETF; no leverage or shorting.",
                "No dividends, taxes, financing, options, or intraday order simulation.",
                "Fixed slippage/fees are assumptions, not an observed fill guarantee.",
                "Open terminal positions are marked, not forcibly liquidated.",
                "Historical simulation is not evidence of future profitability.",
            ],
        },
    }
    if include_baseline:
        benchmark = run_backtest(
            snapshot,
            StrategySpec(kind="buy_hold", allocation=min(strategy.allocation, spec.max_allocation)),
            spec,
            _start=_start,
            _end=end,
            include_baseline=False,
        )
        result["baseline"] = {
            "buy_hold": benchmark["metrics"],
            "buy_hold_spec": benchmark["spec"]["strategy"],
            "cash": {"net_return": "0", "final_equity": str(spec.initial_cash)},
        }
        metrics["excess_return_vs_buy_hold"] = str(
            D(metrics["net_return"]) - D(benchmark["metrics"]["net_return"])
        )
    result["result_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def run_walk_forward(
    snapshot: MarketSnapshot | dict,
    walk: WalkForwardSpec | dict | None = None,
    spec: BacktestSpec | dict | None = None,
) -> dict:
    """Select SMA lookback using training returns only, then score disjoint folds.

    Fold portfolios reset to equal capital. Each fold's terminal mark is a NAV
    valuation; the geometrically linked score is explicitly not a continuous
    executable portfolio. Full folds only; unused trailing sessions are recorded.
    """
    snapshot = MarketSnapshot.model_validate(snapshot)
    walk = WalkForwardSpec.model_validate(walk or {})
    spec = BacktestSpec.model_validate(spec or {})
    if len(snapshot.bars) < walk.train_size + walk.test_size:
        raise QuantError(
            "insufficient_sessions", "dataset is too short for one complete train/test fold"
        )
    folds = []
    test_start = walk.train_size
    compound = D(1)
    while test_start + walk.test_size <= len(snapshot.bars):
        train_start = 0 if walk.anchored else test_start - walk.train_size
        candidates = []
        for lookback in sorted(walk.lookbacks):
            result = run_backtest(
                snapshot,
                StrategySpec(kind="sma", lookback=lookback, allocation=walk.allocation),
                spec,
                _start=train_start,
                _end=test_start,
                include_baseline=False,
            )
            candidates.append(
                {"lookback": lookback, "training_net_return": result["metrics"]["net_return"]}
            )
        winner = max(
            candidates, key=lambda item: (D(item["training_net_return"]), -item["lookback"])
        )
        evaluated = run_backtest(
            snapshot,
            StrategySpec(kind="sma", lookback=winner["lookback"], allocation=walk.allocation),
            spec,
            _start=test_start,
            _end=test_start + walk.test_size,
        )
        compound *= 1 + D(evaluated["metrics"]["net_return"])
        folds.append(
            {
                "index": len(folds),
                "train_start": snapshot.bars[train_start].session.isoformat(),
                "train_end": snapshot.bars[test_start - 1].session.isoformat(),
                "test_start": snapshot.bars[test_start].session.isoformat(),
                "test_end": snapshot.bars[test_start + walk.test_size - 1].session.isoformat(),
                "selected_lookback": winner["lookback"],
                "candidates": candidates,
                "metrics": evaluated["metrics"],
                "baseline": evaluated["baseline"],
                "equity_curve": evaluated["equity_curve"],
                "trades": evaluated["trades"],
            }
        )
        test_start += walk.test_size
    return {
        "status": "completed",
        "spec": {
            "dataset_sha256": snapshot.content_hash,
            "walk_forward": walk.model_dump(mode="json"),
            "execution": spec.model_dump(mode="json"),
        },
        "metrics": {
            "geometrically_linked_fold_return": str(compound - 1),
            "fold_count": len(folds),
        },
        "folds": folds,
        "equity_curve": [],
        "trades": [],
        "validation": {
            "synthetic_data": snapshot.synthetic,
            "nonoverlapping_test_folds": True,
            "selection_metric": "training net return; ties choose shortest lookback",
            "unused_trailing_sessions": len(snapshot.bars) - test_start,
            "limitations": [
                "Reset portfolios per fold; linked return is not continuous trading.",
                "Repeated experiment selection can still overfit; retain every run.",
                "SMA parameter selection only; no profitability claim.",
            ],
        },
    }
