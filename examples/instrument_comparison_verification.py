"""Offline comparison walkthrough using explicitly invented prices and probabilities.

Runs the real Tradier parser and report workflow. No market request, model call,
portfolio mutation or investment result. Each invocation creates a new case.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta

import httpx

from researchdesk.config import Settings
from researchdesk.data.options import TradierOptionsProvider
from researchdesk.domain import ResearchTools
from researchdesk.instrument_workflow import InstrumentComparisonInput, save_instrument_comparison
from researchdesk.options_workflow import OptionsChainInput, acquire_options
from researchdesk.store import Store


def seed(database_url, *, settings=None):
    received = datetime.now(UTC)
    expiry = (received + timedelta(days=30)).date()
    quoted = received - timedelta(minutes=15)

    def symbol(strike, right="C"):
        return f"TEST{expiry:%y%m%d}{right}{strike * 1000:08d}"

    def row(strike, bid, ask, right="C"):
        return {
            "symbol": symbol(strike, right),
            "underlying": "TEST",
            "root_symbol": "TEST",
            "type": "option",
            "option_type": "call" if right == "C" else "put",
            "strike": strike,
            "expiration_date": str(expiry),
            "contract_size": 100,
            "bid": bid,
            "ask": ask,
            "bidsize": 10,
            "asksize": 10,
            "bid_date": int(quoted.timestamp() * 1000),
            "ask_date": int(quoted.timestamp() * 1000) if ask is not None else None,
            "volume": 20,
            "open_interest": 200,
        }

    rows = [row(100, 11.9, 12.1), row(120, 4.0, 4.2), row(100, 9.0, None, "P")]

    class SyntheticProvider(TradierOptionsProvider):
        def chain(self, underlying, expiration):
            return {**super().chain(underlying, expiration), "synthetic": True}

    def transport(request):
        if request.url.path.endswith("/chains"):
            return httpx.Response(200, json={"options": {"option": rows}})
        raise AssertionError("Unexpected network path in synthetic verification")

    store = Store(database_url)
    research = ResearchTools(store, settings or Settings(_env_file=None, database_url=database_url))
    try:
        case = store.create_case(
            "Thesis expressions · synthetic comparison",
            "Engineering walkthrough: a bullish price scenario can still make an expensive "
            "option unattractive. Every TEST quote, price outcome and probability is invented. "
            "This is not a strategy, a model research run or evidence of market returns.",
            workspace_id="quantitative",
        )
        source = store.put_artifact(
            case["id"],
            None,
            "note",
            "Invented scenario assumptions",
            {
                "synthetic": True,
                "description": "For arithmetic verification only: downside 80 with weight 0.3, "
                "modest upside 105 with weight 0.5, large upside 130 with weight 0.2. "
                "These weights were chosen for this example, not estimated from evidence.",
            },
        )
        hypothesis = store.put_artifact(
            case["id"],
            None,
            "hypothesis",
            "Direction versus price paid",
            {
                "prediction": "The invented grid assigns a 70% probability to a stock rise, "
                "but the option premium may consume the assumed upside.",
                "status": "proposed",
                "synthetic": True,
                "mechanism": "A conditional teaching fixture separates "
                "a direction view from its price.",
                "source_artifact_ids": [source["id"]],
            },
        )
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            chain = acquire_options(
                research,
                OptionsChainInput(
                    underlying="TEST",
                    expiration=expiry,
                    purpose="Retain invented premiums for an explicit conditional comparison.",
                ),
                case_id=case["id"],
                provider=SyntheticProvider(
                    "synthetic-not-a-credential", client=client, now=lambda: received
                ),
            )
        args = InstrumentComparisonInput(
            title="A bullish thesis does not make every option attractive",
            purpose="Compare costs and expiration outcomes without confusing them with fills.",
            hypothesis_id=hypothesis["id"],
            chain_artifact_id=chain["id"],
            information_cutoff=datetime.now(UTC),
            scenario_horizon=expiry,
            scenario_source_ids=[source["id"]],
            scenario_rationale="Invented outcome weights expose how premium and whole-contract "
            "sizing change conditional payoffs; these are not calibrated probabilities.",
            assumptions={
                "currency": "USD",
                "capital": "10000",
                "option_fee_per_contract": "1",
                "stock_fee_flat": "1",
                "cash_return_over_horizon": "0.002",
                "adverse_price_bps": "1000",
                "standard_contract_mode": "hypothetical_100_share_usd",
                "standard_contract_assumption": "For this conditional calculation only, assume "
                "premium multiplier 100 and a 100-share deliverable; "
                "provider terms remain unverified.",
                "scenarios": [
                    {"label": "Downside", "underlying_at_expiry": "80", "probability": "0.3"},
                    {"label": "Modest upside", "underlying_at_expiry": "105", "probability": "0.5"},
                    {"label": "Large upside", "underlying_at_expiry": "130", "probability": "0.2"},
                ],
            },
            candidates=[
                {
                    "candidate_id": "call",
                    "label": "Long 100 call",
                    "instrument": "long_call",
                    "long_symbol": symbol(100),
                    "quantity": 3,
                    "rationale": "Pay a premium for upside; "
                    "test whether the supplied outcomes cover its cost.",
                },
                {
                    "candidate_id": "vertical",
                    "label": "100/120 call spread",
                    "instrument": "call_debit_spread",
                    "long_symbol": symbol(100),
                    "short_symbol": symbol(120),
                    "quantity": 3,
                    "rationale": "Offset premium by capping upside; "
                    "compare the tradeoff under the same grid.",
                },
                {
                    "candidate_id": "put",
                    "label": "Long 100 put · missing ask",
                    "instrument": "long_put",
                    "long_symbol": symbol(100, "P"),
                    "rationale": "Keep the unusable alternative visible; "
                    "never invent a missing ask.",
                },
            ],
            stock_reference={
                "kind": "assumed_price",
                "price": "100",
                "quantity": 80,
                "rationale": "An invented stock reference for this engineering example; "
                "no source quote or synchronized stock/options snapshot is asserted.",
            },
        )
        report = save_instrument_comparison(research, args, case_id=case["id"])
        return {
            "case_id": case["id"],
            "report_id": report["id"],
            "sha256": report["sha256"],
            "synthetic": True,
            "execution_eligible": False,
        }
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    print(json.dumps(seed(parser.parse_args().database_url), indent=2))
