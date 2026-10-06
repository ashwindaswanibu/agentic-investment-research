"""Compare nominated expressions on one capital budget using explicit expiry math.

This is a hypothetical, assumption-based comparison of retained observations. It
does not recommend instruments, infer probabilities, assert fills, or implement
options lifecycle accounting. Every alternative independently uses the same budget;
their balances are never summed into a portfolio. Joint expiry payoffs delegate to
the existing evaluate_scenarios calculation.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, Decimal, DecimalException, localcontext
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import StrictModel
from .scenarios import OutcomeScenario, ScenarioSpec, evaluate_scenarios

D = Decimal
_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?$")
_OCC = re.compile(r"^([A-Z][A-Z0-9.]{0,5})(\d{6})([CP])(\d{8})$")
_MAX_VALUE = D("10000000")
_MAX_QUANTITY = 1_000_000  # Matches ScenarioSpec's computational contract.


def _number(value):
    if type(value) not in {str, int, float, Decimal}:
        raise ValueError("A finite bounded decimal is required.")
    text = str(value)
    if len(text) > 64 or not _NUMERIC.fullmatch(text):
        raise ValueError("A finite bounded decimal is required.")
    try:
        number = D(text)
    except DecimalException:
        raise ValueError("A finite bounded decimal is required.") from None
    if (
        not number.is_finite()
        or abs(number) > _MAX_VALUE
        or not -12 <= number.as_tuple().exponent <= 12
        or len(number.as_tuple().digits) > 24
    ):
        raise ValueError("A finite bounded decimal is required.")
    return number


def _money(value):
    return format(value, "f")


def _at(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("An aware ISO timestamp is required.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("An aware ISO timestamp is required.")
    return parsed.astimezone(UTC)


def _day(value):
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError("An ISO date is required.")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("An ISO date is required.")
    return parsed


class ComparisonAssumptions(StrictModel):
    currency: Literal["USD"]
    capital: Decimal = Field(gt=0, le=_MAX_VALUE)
    scenarios: tuple[OutcomeScenario, ...] = Field(min_length=1, max_length=20)
    option_fee_per_contract: Decimal = Field(ge=0, le=1000)
    stock_fee_flat: Decimal = Field(ge=0, le=100000)
    cash_return_over_horizon: Decimal = Field(ge=-1, le=1)
    adverse_price_bps: Decimal = Field(ge=0, le=10000)
    standard_contract_mode: Literal["hypothetical_100_share_usd"]
    standard_contract_assumption: str = Field(min_length=20, max_length=2000)

    _numbers = field_validator(
        "capital",
        "option_fee_per_contract",
        "stock_fee_flat",
        "cash_return_over_horizon",
        "adverse_price_bps",
        mode="before",
    )(_number)

    @field_validator("scenarios", mode="before")
    @classmethod
    def bounded_scenarios(cls, values):
        if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 20:
            raise ValueError("Provide 1–20 outcome scenarios.")
        normalized = []
        for value in values:
            item = value.model_dump() if isinstance(value, OutcomeScenario) else value
            if not isinstance(item, dict):
                raise ValueError("Scenarios require structured observations.")
            item = dict(item)
            item["underlying_at_expiry"] = _number(item.get("underlying_at_expiry"))
            if item.get("probability") is not None:
                item["probability"] = _number(item["probability"])
            normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def coherent_grid(self):
        if len({scenario.label for scenario in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario labels must be distinct.")
        probabilities = [scenario.probability for scenario in self.scenarios]
        if any(value is not None for value in probabilities):
            if any(value is None for value in probabilities) or sum(probabilities) != D(1):
                raise ValueError("Give all probabilities summing exactly to one, or none.")
        if not self.standard_contract_assumption.strip():
            raise ValueError("State the hypothetical standard-contract assumption.")
        return self


class InstrumentCandidate(StrictModel):
    candidate_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,49}$")
    label: str = Field(min_length=1, max_length=200)
    instrument: Literal["long_call", "long_put", "call_debit_spread", "put_debit_spread"]
    long_symbol: str = Field(min_length=1, max_length=30)
    short_symbol: str | None = Field(default=None, min_length=1, max_length=30)
    quantity: int | None = Field(default=None, ge=1, le=_MAX_QUANTITY, strict=True)
    rationale: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def correct_leg_count(self):
        if self.candidate_id in {"cash", "stock"}:
            raise ValueError("cash and stock are reserved baseline identifiers.")
        if self.instrument.endswith("_spread") != (self.short_symbol is not None):
            raise ValueError("Nominate two legs for a spread and one for a long option.")
        if self.long_symbol == self.short_symbol:
            raise ValueError("A spread must use two distinct contracts.")
        return self


class _Unavailable(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _issue(code, message):
    return {"code": code, "message": message}


def _row(candidate_id, label, instrument, rationale):
    return {
        "candidate_id": candidate_id,
        "label": label,
        "instrument": instrument,
        "rationale": rationale,
        "sizing_basis": "maximum_affordable",
        "requested_quantity": None,
        "status": "unavailable",
        "issues": [],
        "base": None,
        "adverse": None,
        "legs": [],
    }


def _contract(symbol, records, underlying, expiration, received_at, side):
    record = records.get(symbol)
    if record is None:
        raise _Unavailable(
            "contract_missing", "A nominated contract is absent from the saved chain."
        )
    try:
        match = _OCC.fullmatch(symbol)
        if match is None:
            raise ValueError("Invalid OCC identity.")
        root, compact_date, right, compact_strike = match.groups()
        occ_expiry = date(
            2000 + int(compact_date[:2]), int(compact_date[2:4]), int(compact_date[4:])
        )
        strike = _number(record.get("strike"))
        if (
            record.get("symbol") != symbol
            or record.get("underlying") != underlying
            or _day(record.get("expiration")) != expiration
            or occ_expiry != expiration
            or record.get("option_type") != {"C": "call", "P": "put"}[right]
            or strike <= 0
            or strike != D(compact_strike) / 1000
        ):
            raise ValueError("Inconsistent contract identity.")
    except (ValueError, TypeError, OverflowError):
        raise _Unavailable(
            "contract_identity_invalid", "Contract identity or expiration is inconsistent."
        ) from None
    if (
        root != underlying.replace("/", ".")
        or record.get("root_symbol") != root
        or type(record.get("contract_size")) is not int
        or record["contract_size"] != 100
        or record.get("contract_status") == "unsupported"
    ):
        raise _Unavailable(
            "contract_terms_unsupported",
            "This calculation only assumes standard-root, reported-size-100 contracts; "
            "adjusted, missing or conflicting terms are unavailable.",
        )
    try:
        if (
            record.get("premium_multiplier") is not None
            and _number(record["premium_multiplier"]) != 100
        ):
            raise ValueError("Incompatible multiplier.")
        deliverable = record.get("deliverable")
        if deliverable is not None:
            # Only this explicit simple shape is understood. Unknown terms must not
            # be erased by a generic standard-contract assumption.
            if (
                not isinstance(deliverable, dict)
                or set(deliverable) != {"underlying", "shares", "cash", "currency"}
                or deliverable["underlying"] != underlying
                or type(deliverable["shares"]) is not int
                or deliverable["shares"] != 100
                or _number(deliverable["cash"]) != 0
                or deliverable["currency"] != "USD"
            ):
                raise ValueError("Unqualified or incompatible deliverable.")
        if (
            record.get("exercise_style") not in {None, "american", "european"}
            or record.get("settlement_type") not in {None, "physical"}
            or record.get("currency") not in {None, "USD"}
        ):
            raise ValueError("Incompatible or unsupported contract terms.")
    except (ValueError, TypeError):
        raise _Unavailable(
            "contract_terms_conflict",
            "Present contract terms are incompatible or insufficiently "
            "qualified; the standard-contract assumption cannot overwrite them.",
        ) from None
    try:
        bid, ask = _number(record.get("bid")), _number(record.get("ask"))
        if min(bid, ask) <= 0 or bid > ask:
            raise ValueError("Nonpositive or crossed quote.")
    except ValueError:
        raise _Unavailable(
            "quote_invalid", "Both retained bid and ask must be positive and uncrossed."
        ) from None
    try:
        bid_at, ask_at = _at(record.get("bid_at")), _at(record.get("ask_at"))
        if max(bid_at, ask_at) > received_at:
            raise ValueError("Quote observation is later than receipt.")
    except ValueError:
        raise _Unavailable(
            "quote_time_invalid",
            "Both market timestamps must be known and no later than chain receipt.",
        ) from None
    return {
        "symbol": symbol,
        "side": side,
        "option_type": record["option_type"],
        "strike": _money(strike),
        "expiration": expiration.isoformat(),
        "bid": _money(bid),
        "ask": _money(ask),
        "selected_price": _money(ask if side == "buy" else bid),
        "market_at": (ask_at if side == "buy" else bid_at).isoformat(),
        "bid_at": bid_at.isoformat(),
        "ask_at": ask_at.isoformat(),
        "received_at": received_at.isoformat(),
        "contract_size": 100,
        "contract_terms_status": "assumed_not_verified",
        "assumed_premium_multiplier": 100,
        "assumed_share_deliverable": 100,
        "size_unit": record.get("size_unit"),
        "quoted_size": record.get("ask_size" if side == "buy" else "bid_size"),
        "source_issues": record.get("issues", []),
    }


def _result(assumptions, instrument, quantity, entry_price, fees, strike=None, short_strike=None):
    capital = assumptions.capital
    units = quantity * (1 if instrument == "stock" else 100)
    cost = entry_price * units + fees
    result = {
        "status": "computed",
        "quantity": quantity,
        "quantity_unit": (
            "shares"
            if instrument == "stock"
            else "spreads"
            if instrument in {"call_debit_spread", "put_debit_spread"}
            else "contracts"
        ),
        "entry_cost": _money(cost),
        "required_capital": _money(cost),
        "remaining_cash": None,
        "fees": _money(fees),
        "expiry_loss_bound": None,
        "position_expiry_loss_bound": None,
        "scenario_worst_pnl": None,
        "assumption_weighted_pnl": None,
        "excess_vs_cash": None,
        "scenarios": [],
        "issues": [],
    }
    if cost > capital:
        result["status"] = "not_affordable"
        result["issues"] = [
            _issue(
                "adverse_budget_exceeded",
                "The unchanged position exceeds the budget at adverse prices; "
                "no borrowing, resizing or negative cash was simulated.",
            )
        ]
        return result
    if short_strike is not None and entry_price > abs(strike - short_strike):
        result["status"] = "unavailable"
        result["issues"] = [
            _issue(
                "debit_exceeds_width",
                "The adverse debit exceeds spread width and falls outside "
                "the existing debit-spread calculator's supported contract.",
            )
        ]
        return result
    evaluation = evaluate_scenarios(
        ScenarioSpec(
            instrument=instrument,
            entry_price=entry_price,
            quantity=quantity,
            strike=strike,
            short_strike=short_strike,
            multiplier=100,
            fees=fees,
            scenarios=assumptions.scenarios,
            assumptions=assumptions.standard_contract_assumption,
        )
    )
    remaining = capital - cost
    terminal_cash = remaining * (1 + assumptions.cash_return_over_horizon)
    cash_pnl = capital * assumptions.cash_return_over_horizon
    outcomes = []
    for row in evaluation["scenarios"]:
        terminal_capital = D(row["terminal_value"]) + terminal_cash
        pnl = terminal_capital - capital
        outcomes.append(
            {
                "label": row["label"],
                "underlying_at_expiry": row["underlying_at_expiry"],
                "probability": row["probability"],
                "pnl": _money(pnl),
                "terminal_capital": _money(terminal_capital),
                "return_on_capital": _money(pnl / capital),
                "excess_vs_cash": _money(pnl - cash_pnl),
            }
        )
    weighted = None
    if assumptions.scenarios[0].probability is not None:
        weighted = sum(D(row["pnl"]) * D(row["probability"]) for row in outcomes)
    result.update(
        {
            "remaining_cash": _money(remaining),
            "expiry_loss_bound": _money(max(D(0), capital - terminal_cash)),
            "position_expiry_loss_bound": evaluation["maximum_loss_at_expiry"],
            "scenario_worst_pnl": _money(min(D(row["pnl"]) for row in outcomes)),
            "assumption_weighted_pnl": _money(weighted) if weighted is not None else None,
            "excess_vs_cash": _money(weighted - cash_pnl) if weighted is not None else None,
            "scenarios": outcomes,
        }
    )
    return result


def _size(capital, price, multiplier, fee_per_unit, flat_fee=0, requested_quantity=None):
    unit_cost = price * multiplier + fee_per_unit
    if requested_quantity is not None:
        if type(requested_quantity) is not int or not 1 <= requested_quantity <= _MAX_QUANTITY:
            raise _Unavailable(
                "quantity_invalid", "Requested quantity must be 1–1,000,000 whole units."
            )
        requested_cost = requested_quantity * unit_cost + flat_fee
        if requested_cost > capital:
            raise _Unavailable(
                "requested_quantity_unaffordable",
                f"The requested position requires {_money(requested_cost)} including fees; "
                "it exceeds the stated budget and was not resized.",
            )
        return requested_quantity
    quantity = int(((capital - flat_fee) / unit_cost).to_integral_value(rounding=ROUND_FLOOR))
    if quantity < 1:
        raise _Unavailable(
            "no_affordable_unit",
            f"One whole unit requires {_money(unit_cost + flat_fee)}; "
            "the stated budget cannot fund it including fees.",
        )
    if quantity > _MAX_QUANTITY:
        raise _Unavailable(
            "quantity_limit",
            "Maximum affordable sizing exceeds the calculator's one-million-unit limit.",
        )
    return quantity


def _cash(assumptions):
    capital = assumptions.capital
    pnl = capital * assumptions.cash_return_over_horizon
    weighted = assumptions.scenarios[0].probability is not None
    result = {
        "status": "computed",
        "quantity": 0,
        "quantity_unit": "cash",
        "entry_cost": "0",
        "required_capital": "0",
        "remaining_cash": _money(capital),
        "fees": "0",
        "expiry_loss_bound": _money(max(D(0), -pnl)),
        "position_expiry_loss_bound": "0",
        "scenario_worst_pnl": _money(pnl),
        "assumption_weighted_pnl": _money(pnl) if weighted else None,
        "excess_vs_cash": "0" if weighted else None,
        "issues": [],
        "scenarios": [
            {
                "label": scenario.label,
                "underlying_at_expiry": _money(scenario.underlying_at_expiry),
                "probability": _money(scenario.probability)
                if scenario.probability is not None
                else None,
                "pnl": _money(pnl),
                "terminal_capital": _money(capital + pnl),
                "return_on_capital": _money(assumptions.cash_return_over_horizon),
                "excess_vs_cash": "0",
            }
            for scenario in assumptions.scenarios
        ],
    }
    row = _row(
        "cash",
        "Cash",
        "cash",
        "Keep the entire budget at the explicitly assumed horizon cash return.",
    )
    row.update(status="available", base=result, adverse={**result}, sizing_basis="cash")
    return row


def _stock(assumptions, reference, underlying):
    row = _row(
        "stock",
        "Underlying stock",
        "stock",
        "Compare the nominated options with whole shares on the same budget.",
    )
    if reference is None:
        row["issues"] = [
            _issue(
                "stock_reference_missing",
                "No attributable or explicitly assumed stock price was supplied.",
            )
        ]
        return row
    try:
        if not isinstance(reference, dict) or reference.get("underlying") != underlying:
            raise _Unavailable(
                "stock_reference_invalid", "Stock reference must match the chain underlying."
            )
        requested_quantity = reference.get("quantity")
        row.update(
            sizing_basis="requested_quantity"
            if requested_quantity is not None
            else "maximum_affordable",
            requested_quantity=requested_quantity,
        )
        try:
            price = _number(reference.get("price"))
            if price <= 0:
                raise ValueError("Positive stock price required.")
        except ValueError:
            raise _Unavailable(
                "stock_price_invalid", "Stock price must be finite, bounded and positive."
            ) from None
        if (
            type(reference.get("assumption")) is not bool
            or not isinstance(reference.get("source"), str)
            or not reference["source"].strip()
            or not isinstance(reference.get("rationale"), str)
            or not reference["rationale"].strip()
            or len(reference["source"]) > 2000
            or len(reference["rationale"]) > 4000
        ):
            raise _Unavailable(
                "stock_reference_invalid",
                "Declare source, rationale and whether the price is assumed.",
            )
        for field in ("observed_at", "received_at"):
            if reference.get(field) is not None:
                try:
                    _at(reference[field])
                except ValueError:
                    raise _Unavailable(
                        "stock_time_invalid", "Stock timestamps must be aware ISO times."
                    ) from None
        if reference.get("observation_session") is not None:
            try:
                _day(reference["observation_session"])
            except ValueError:
                raise _Unavailable(
                    "stock_time_invalid", "Stock session must be an ISO date."
                ) from None
        row["legs"] = [
            {
                "side": "buy",
                "underlying": underlying,
                "price": _money(price),
                "selected_price": _money(price),
                "source": reference["source"],
                "rationale": reference["rationale"],
                "assumption": reference["assumption"],
                "observed_at": reference.get("observed_at"),
                "received_at": reference.get("received_at"),
                "observation_session": (
                    _day(reference["observation_session"]).isoformat()
                    if reference.get("observation_session") is not None
                    else None
                ),
            }
        ]
        row["issues"] = [
            _issue(
                "stock_price_alignment_unverified",
                "The stock reference is not asserted contemporaneous "
                "with the option quotes; retain its source and timing when "
                "interpreting the comparison.",
            )
        ]
        if reference["assumption"]:
            row["issues"].append(
                _issue(
                    "stock_price_assumed",
                    "Stock entry price is an explicit hypothetical assumption.",
                )
            )
        quantity = _size(
            assumptions.capital,
            price,
            1,
            0,
            assumptions.stock_fee_flat,
            requested_quantity=requested_quantity,
        )
        fees = assumptions.stock_fee_flat
        row.update(
            status="available",
            base=_result(assumptions, "stock", quantity, price, fees),
            adverse=_result(
                assumptions,
                "stock",
                quantity,
                price * (1 + assumptions.adverse_price_bps / 10000),
                fees,
            ),
        )
    except _Unavailable as exc:
        row["issues"].append(_issue(exc.code, exc.message))
    return row


def _compare_instruments(assumptions, candidates, chain, stock_reference=None):
    """Pure repeatable comparison; root workflow owns cutoff/provenance validation.

    A later stock observation may be valid at the report cutoff, even if the chain
    was collected earlier. This function does not substitute chain.received_at for
    that cutoff. Stock availability and input artifact bindings belong upstream.
    """
    assumptions = ComparisonAssumptions.model_validate(
        assumptions.model_dump() if isinstance(assumptions, ComparisonAssumptions) else assumptions
    )
    if not isinstance(candidates, (list, tuple)) or not 1 <= len(candidates) <= 20:
        raise ValueError("Nominate 1–20 options alternatives.")
    candidates = [
        InstrumentCandidate.model_validate(
            candidate.model_dump() if isinstance(candidate, InstrumentCandidate) else candidate
        )
        for candidate in candidates
    ]
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise ValueError("Candidate identifiers must be unique.")
    if not isinstance(chain, dict) or chain.get("schema_version") != "options_chain.v1":
        raise ValueError("A retained options_chain.v1 input is required.")
    underlying = chain.get("underlying")
    if not isinstance(underlying, str) or not re.fullmatch(r"[A-Z][A-Z0-9/.\-]{0,14}", underlying):
        raise ValueError("Chain underlying is invalid.")
    expiration, received_at = _day(chain.get("expiration")), _at(chain.get("received_at"))
    source_records = chain.get("contracts")
    if not isinstance(source_records, list) or len(source_records) > 1000:
        raise ValueError("Chain contract collection is invalid.")
    records = {}
    for record in source_records:
        if not isinstance(record, dict) or not isinstance(record.get("symbol"), str):
            raise ValueError("Chain contract collection is invalid.")
        if record["symbol"] in records:
            raise ValueError("Chain contains duplicate contract identifiers.")
        records[record["symbol"]] = record
    results = [_cash(assumptions), _stock(assumptions, stock_reference, underlying)]
    for candidate in candidates:
        row = _row(
            candidate.candidate_id, candidate.label, candidate.instrument, candidate.rationale
        )
        row.update(
            sizing_basis="requested_quantity"
            if candidate.quantity is not None
            else "maximum_affordable",
            requested_quantity=candidate.quantity,
        )
        results.append(row)
        try:
            long = _contract(
                candidate.long_symbol, records, underlying, expiration, received_at, "buy"
            )
            row["legs"].append(long)
            required_type = "call" if "call" in candidate.instrument else "put"
            if long["option_type"] != required_type:
                raise _Unavailable(
                    "option_type_mismatch", "Contract type does not match the nominated expression."
                )
            short = None
            if candidate.short_symbol:
                short = _contract(
                    candidate.short_symbol, records, underlying, expiration, received_at, "sell"
                )
                row["legs"].append(short)
                if short["option_type"] != required_type:
                    raise _Unavailable(
                        "option_type_mismatch",
                        "Both spread legs must have the nominated option type.",
                    )
            strike = D(long["strike"])
            short_strike = D(short["strike"]) if short else None
            debit = D(long["selected_price"]) - (D(short["selected_price"]) if short else D(0))
            if debit <= 0:
                raise _Unavailable(
                    "nonpositive_debit",
                    "Retained quotes do not form a positive net-debit expression.",
                )
            if short:
                width = short_strike - strike if required_type == "call" else strike - short_strike
                if width <= 0 or debit > width:
                    raise _Unavailable(
                        "invalid_spread",
                        "Strike ordering or quoted net debit is inconsistent "
                        "with this debit spread.",
                    )
            leg_count = 2 if short else 1
            fee_per_unit = assumptions.option_fee_per_contract * leg_count
            quantity = _size(
                assumptions.capital,
                debit,
                100,
                fee_per_unit,
                requested_quantity=candidate.quantity,
            )
            fees = quantity * fee_per_unit
            stress = assumptions.adverse_price_bps / 10000
            adverse_debit = D(long["selected_price"]) * (1 + stress)
            if short:
                adverse_debit -= D(short["selected_price"]) * (1 - stress)
            row.update(
                status="available",
                base=_result(
                    assumptions, candidate.instrument, quantity, debit, fees, strike, short_strike
                ),
                adverse=_result(
                    assumptions,
                    candidate.instrument,
                    quantity,
                    adverse_debit,
                    fees,
                    strike,
                    short_strike,
                ),
            )
            row["issues"] = [
                _issue(
                    "contract_terms_assumed",
                    "Payoffs assume 100 premium units and a 100-share deliverable; "
                    "those terms remain unverified in the saved chain.",
                ),
                _issue(
                    "quote_execution_unverified",
                    "Retained quotes supply hypothetical entry inputs, not fills; "
                    "quoted size, delay and liquidity do not establish executable capacity.",
                ),
            ]
        except _Unavailable as exc:
            row["issues"].append(_issue(exc.code, exc.message))
    return {
        "schema_version": "instrument_comparison.v1",
        "execution_eligible": False,
        "underlying": underlying,
        "expiration": expiration.isoformat(),
        "currency": "USD",
        "capital": _money(assumptions.capital),
        "assumptions": assumptions.model_dump(mode="json"),
        "probability_basis": (
            "supplied_scenario_assumptions"
            if assumptions.scenarios[0].probability is not None
            else "unweighted_scenarios"
        ),
        "candidates": results,
        "method": {
            "sizing": "Use an investigator-requested whole quantity when supplied; otherwise "
            "the maximum affordable whole units for each alternative independently. "
            "Both include entry fees and preserve the common budget.",
            "adverse_sizing": "Same base quantity; unaffordable adverse inputs have no "
            "simulated borrowing or resizing.",
            "cash": "The same stated horizon cash return applies to the full cash baseline "
            "and unused cash in every alternative.",
            "probabilities": "Supplied scenario assumptions only; no probabilities "
            "or expected returns are inferred.",
        },
        "limitations": [
            "Expiry payoff comparison, not an options backtest, recommendation "
            "or simulated execution.",
            "Alternatives independently reuse one hypothetical budget and must not "
            "be summed into an account.",
            "Standard-contract terms are explicit assumptions, not inferred or "
            "verified deliverables.",
            "No pre-expiry valuation, implied-volatility forecast, exercise funding, "
            "early assignment, "
            "dividends, taxes, settlement fees or liquidation costs.",
            "Spreads assume joint expiry settlement; analytical loss bounds exclude "
            "lifecycle and legging risk.",
            "Scenario-worst outcomes cover only the nominated grid; analytical expiry "
            "bounds cover all nonnegative prices.",
        ],
    }


def compare_instruments(assumptions, candidates, chain, stock_reference=None):
    # Bounded input precision, quantity and grid sizes make 80 digits sufficient
    # for exact money products and sums; division metrics are explicitly ratios.
    # Local context also prevents callers' ambient Decimal settings changing sizing.
    with localcontext() as context:
        context.prec = 80
        return _compare_instruments(assumptions, candidates, chain, stock_reference)
