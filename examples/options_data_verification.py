"""Reproducible, explicitly synthetic options inspector verification.

Exercises the real Tradier parser and acquisition/store path with a mock HTTP
transport. No credentials, market network access, model or trading are involved.
Creates a new clearly labeled case; never overwrites an earlier case or snapshot.
Run from the repository with an explicit SQLite database URL for the preview.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

import httpx

from researchdesk.config import Settings
from researchdesk.data.options import TradierOptionsProvider
from researchdesk.domain import ResearchTools
from researchdesk.options_workflow import (
    OptionsChainInput,
    OptionsExpirationsInput,
    acquire_options,
)
from researchdesk.store import Store

RECEIVED = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
QUOTE_MILLIS = int((RECEIVED - timedelta(minutes=15)).timestamp() * 1000)


def contract(strike, right, **overrides):
    return {
        "symbol": f"TEST261016{right}{strike * 1000:08d}",
        "underlying": "TEST",
        "root_symbol": "TEST",
        "type": "option",
        "option_type": "call" if right == "C" else "put",
        "strike": strike,
        "expiration_date": "2026-10-16",
        "contract_size": 100,
        "bid": 2.10,
        "ask": 2.35,
        "bidsize": 12,
        "asksize": 8,
        "bid_date": QUOTE_MILLIS,
        "ask_date": QUOTE_MILLIS,
        "volume": 120,
        "open_interest": 300,
        **overrides,
    }


class SyntheticTradier(TradierOptionsProvider):
    """Mark every parsed result as a software fixture before it is retained."""

    def expirations(self, underlying):
        return {**super().expirations(underlying), "synthetic": True}

    def chain(self, underlying, expiration):
        return {**super().chain(underlying, expiration), "synthetic": True}


def seed(database_url):
    rows = [
        contract(95, "C", bid=6.20, ask=6.55),
        contract(95, "P", bid=0.80, ask=1.00, bid_date=QUOTE_MILLIS - 60000),
        contract(100, "C"),
        contract(100, "P", bid=1.90, ask=None, ask_date=None),
        contract(105, "C", bid=0, bidsize=0, volume=0, open_interest=None),
        contract(105, "P", bid=5.30, ask=5.10),
    ]

    def transport(request):
        if request.url.path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": ["2026-10-16"]}})
        if request.url.path.endswith("/chains"):
            return httpx.Response(200, json={"options": {"option": rows}})
        raise AssertionError("Unexpected endpoint in offline verification")

    settings = Settings(_env_file=None, database_url=database_url, read_only=False)
    store = Store(database_url)
    try:
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            provider = SyntheticTradier(
                "synthetic-fixture-token", client=client, now=lambda: RECEIVED
            )
            research = ResearchTools(store, settings)
            case = store.create_case(
                "Options data · synthetic verification",
                "Engineering fixture: verify delayed quote provenance, missing values and "
                "contract inspection. These are invented TEST prices, not a strategy, "
                "real market data, a model run or evidence of profitability.",
                workspace_id="quantitative",
            )
            dates = acquire_options(
                research,
                OptionsExpirationsInput(
                    underlying="TEST",
                    purpose="Verify expiration discovery with an offline fixture.",
                ),
                case_id=case["id"],
                provider=provider,
            )
            chain = acquire_options(
                research,
                OptionsChainInput(
                    underlying="TEST",
                    expiration="2026-10-16",
                    purpose="Inspect calls and puts while keeping quote time separate from "
                    "receipt time. Includes missing, zero, crossed and asynchronous quotes.",
                    source_artifact_ids=[dates["id"]],
                ),
                case_id=case["id"],
                provider=provider,
            )
            return {
                "synthetic": True,
                "case_id": case["id"],
                "artifact_id": chain["id"],
                "sha256": chain["sha256"],
                "case_path": f"/cases/{case['id']}",
                "contracts": len(chain["content"]["contracts"]),
            }
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    print(json.dumps(seed(parser.parse_args().database_url), indent=2))
