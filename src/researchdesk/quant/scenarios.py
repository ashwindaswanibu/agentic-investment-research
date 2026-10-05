"""Explicit assumption-based arithmetic, separate from market forecasts or fills."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel

D = Decimal


class OutcomeScenario(StrictModel):
    label: str = Field(min_length=1, max_length=200)
    underlying_at_expiry: Decimal = Field(ge=0)
    probability: Decimal | None = Field(default=None, ge=0, le=1)


class ScenarioSpec(StrictModel):
    instrument: Literal["stock", "long_call", "long_put", "call_debit_spread", "put_debit_spread"]
    entry_price: Decimal = Field(
        gt=0, description="stock price or net premium per underlying share"
    )
    quantity: int = Field(ge=1, le=1000000, strict=True)
    strike: Decimal | None = Field(default=None, gt=0)
    short_strike: Decimal | None = Field(default=None, gt=0)
    multiplier: int = Field(default=100, ge=1, le=10000, strict=True)
    fees: Decimal = Field(default=D(0), ge=0)
    scenarios: tuple[OutcomeScenario, ...] = Field(min_length=1, max_length=100)
    assumptions: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def coherent_structure(self) -> ScenarioSpec:
        if self.instrument != "stock" and self.strike is None:
            raise ValueError("option scenarios require a strike")
        spread = self.instrument.endswith("_spread")
        if spread:
            if self.short_strike is None:
                raise ValueError("debit spreads require the short strike")
            width = (
                self.short_strike - self.strike
                if self.instrument == "call_debit_spread"
                else self.strike - self.short_strike
            )
            if width <= 0 or self.entry_price > width:
                raise ValueError("debit spread strikes or net debit are inconsistent")
        elif self.short_strike is not None:
            raise ValueError("short_strike is only supported for debit spreads")
        if self.instrument == "stock" and self.strike is not None:
            raise ValueError("stock has no option strike")
        probabilities = [item.probability for item in self.scenarios]
        if any(p is not None for p in probabilities):
            if any(p is None for p in probabilities) or sum(probabilities) != D(1):
                raise ValueError(
                    "provide probabilities for all scenarios summing exactly to one, or none"
                )
        return self


def evaluate_scenarios(spec: ScenarioSpec | dict) -> dict:
    spec = ScenarioSpec.model_validate(spec)
    units = spec.quantity * (1 if spec.instrument == "stock" else spec.multiplier)
    debit = units * spec.entry_price + spec.fees
    rows = []
    for item in spec.scenarios:
        spot = item.underlying_at_expiry
        if spec.instrument == "stock":
            payoff = spot
        elif spec.instrument in ("long_call", "call_debit_spread"):
            payoff = max(D(0), spot - spec.strike)
            if spec.short_strike is not None:
                payoff -= max(D(0), spot - spec.short_strike)
        else:
            payoff = max(D(0), spec.strike - spot)
            if spec.short_strike is not None:
                payoff -= max(D(0), spec.short_strike - spot)
        pnl = payoff * units - debit
        rows.append(
            {
                "label": item.label,
                "underlying_at_expiry": str(spot),
                "probability": str(item.probability) if item.probability is not None else None,
                "terminal_value": str(payoff * units),
                "pnl": str(pnl),
                "return_on_debit": str(pnl / debit),
            }
        )
    expected = None
    if spec.scenarios[0].probability is not None:
        expected = sum(
            D(row["pnl"]) * item.probability for row, item in zip(rows, spec.scenarios, strict=True)
        )
    return {
        "status": "completed",
        "spec": spec.model_dump(mode="json"),
        "initial_debit": str(debit),
        "maximum_loss_at_expiry": str(debit),
        "scenarios": rows,
        "assumption_weighted_pnl": str(expected) if expected is not None else None,
        "validation": {
            "execution_eligible": False,
            "limitations": [
                "Expiration payoff scenarios, not market forecasts or executable orders.",
                "Any probabilities are supplied assumptions, not inferred clinical odds.",
                "No pre-expiry volatility/time-value model, early assignment, taxes or dividends.",
                "Spread payoff assumes joint settlement; broker/lifecycle risk is excluded.",
            ],
        },
    }


def compare_binary_rates(
    treatment_events: int, treatment_n: int, control_events: int, control_n: int
) -> dict:
    """Independent-binomial descriptive estimates, not a trial success forecast.

    Wilson intervals for each rate; Newcombe hybrid-score interval for difference.
    Relative-risk log interval is omitted at boundaries instead of injecting
    undisclosed pseudo-counts. Does not adjust for trial design or multiplicity.
    """
    values = (treatment_events, treatment_n, control_events, control_n)
    if any(type(v) is not int for v in values):
        raise ValueError("event counts and denominators must be integers")
    if (
        min(treatment_n, control_n) <= 0
        or not 0 <= treatment_events <= treatment_n
        or not 0 <= control_events <= control_n
    ):
        raise ValueError("counts must be between zero and their positive denominator")
    z = 1.959963984540054
    p, q = treatment_events / treatment_n, control_events / control_n

    def wilson(rate: float, n: int) -> list[float]:
        center = (rate + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return [max(0.0, center - half), min(1.0, center + half)]

    p_interval, q_interval = wilson(p, treatment_n), wilson(q, control_n)
    # Hybrid-score interval remains informative at zero/all-event boundaries.
    difference_interval = [
        max(-1.0, p - q - math.sqrt((p - p_interval[0]) ** 2 + (q_interval[1] - q) ** 2)),
        min(1.0, p - q + math.sqrt((p_interval[1] - p) ** 2 + (q - q_interval[0]) ** 2)),
    ]
    rr = p / q if q else None
    rr_ci = None
    if 0 < treatment_events < treatment_n and 0 < control_events < control_n:
        log_se = math.sqrt(
            1 / treatment_events - 1 / treatment_n + 1 / control_events - 1 / control_n
        )
        rr_ci = [math.exp(math.log(rr) - z * log_se), math.exp(math.log(rr) + z * log_se)]
    return {
        "treatment_rate": p,
        "control_rate": q,
        "risk_difference": p - q,
        "treatment_wilson_95": p_interval,
        "control_wilson_95": q_interval,
        "risk_difference_newcombe_95": difference_interval,
        "relative_risk": rr,
        "relative_risk_log_95": rr_ci,
        "limitations": [
            "Descriptive independent-binomial comparison; no covariate or multiplicity adjustment.",
            "Score intervals are approximate and do not establish clinical significance.",
            "Endpoint meaning, prespecification, missingness and design require source review.",
        ],
    }
