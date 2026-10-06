"""Exercise the real forecast API using clearly invented evidence, without credentials.

Creates one new synthetic case, waits for its short actual event window to close,
then records an outcome and a correction. No clocks, registration times or market
events are fabricated by the API. The event, evidence and probabilities ARE
invented engineering fixtures, never a real forecast or model run.
Requires the local development/test dependencies. No network requests are made.
"""

import argparse
import json
import math
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from researchdesk.api import create_app
from researchdesk.config import Settings
from researchdesk.store import Store


def seed(database_url):
    store = Store(database_url)
    settings = Settings(_env_file=None, database_url=database_url, read_only=False)
    try:
        case = store.create_case(
            "Forecasts · synthetic outcome review",
            "An invented TEST study illustrates registration, source-backed operator "
            "resolution and correction history. All probabilities, reports and outcomes "
            "are fabricated for software verification. No model or market result is claimed.",
            workspace_id="clinical",
        )
        source = store.put_artifact(
            case["id"],
            None,
            "evidence",
            "Invented TEST study plan",
            {
                "synthetic": True,
                "description": "Invented plan: the fictional TEST study will issue a report "
                "during this engineering demonstration's short event window. The fixed "
                "target is at least 50 protocol-defined responses among 100 participants. "
                "The 70% forecast and 50% baseline are illustrative assumptions.",
            },
        )
        hypothesis = store.put_artifact(
            case["id"],
            None,
            "hypothesis",
            "TEST response threshold · invented mechanism",
            {
                "synthetic": True,
                "status": "proposed",
                "prediction": "The invented TEST report will describe at least 50 responses "
                "among the fixed 100 participants.",
                "mechanism": "An explicitly fabricated mechanism for testing a recorded "
                "belief against a later invented report.",
                "source_artifact_ids": [source["id"]],
            },
        )

        with TestClient(create_app(settings=settings, store=store)) as client:

            def post(path, body, key=None, expected=201):
                response = client.post(
                    path,
                    json=body,
                    headers={"Idempotency-Key": key or str(uuid4())},
                )
                assert response.status_code == expected, response.text
                return response.json()

            now = datetime.now(UTC)
            closes = now + timedelta(seconds=6)
            common = {
                "hypothesis_id": hypothesis["id"],
                "hypothesis_sha256": hypothesis["sha256"],
                "question": "Will the fictional TEST report meet the fixed response threshold?",
                "opens_at": (now + timedelta(seconds=5)).isoformat(),
                "closes_at": closes.isoformat(),
                "yes_rule": "The TEST report states at least 50 protocol-defined responses "
                "among the fixed 100 participants; a correction supersedes the earlier report.",
                "no_rule": "The TEST report states fewer than 50 responses among the same "
                "100 participants. Missing or conflicting evidence is not a No outcome.",
                "unresolvable_rule": "No usable report or verified denominator is available, "
                "or the report cannot be reconciled under the predeclared definition.",
                "resolution_source": "Explicitly invented TEST report retained as evidence "
                "in this synthetic case, including any subsequent correction.",
                "status": "forecast",
                "probability": 0.7,
                "baseline_probability": 0.5,
                "baseline_rationale": "An illustrative 50% comparison declared before the "
                "window. It is not an empirical clinical base rate.",
                "source_artifact_ids": [source["id"]],
            }
            path = f"/api/cases/{case['id']}/forecasts"
            forecast = post(path, common)
            missing = post(
                path,
                {
                    **common,
                    "question": "Will the fictional TEST extension meet its response target?",
                },
            )
            due = post(
                path,
                {
                    **common,
                    "question": "Will the fictional TEST follow-up confirm the response target?",
                },
            )
            pending = post(
                path,
                {
                    **common,
                    "question": "Will the fictional TEST replication meet its response target?",
                    "opens_at": (now + timedelta(days=10)).isoformat(),
                    "closes_at": (now + timedelta(days=30)).isoformat(),
                },
            )
            abstained = post(
                path,
                {
                    **common,
                    "question": "Will the fictional TEST subgroup meet its response target?",
                    "opens_at": (now + timedelta(days=10)).isoformat(),
                    "closes_at": (now + timedelta(days=30)).isoformat(),
                    "status": "abstain",
                    "probability": None,
                    "abstention_reason": "This invented subgroup has no stable denominator; "
                    "the example retains abstention instead of assigning "
                    "an unsupported probability.",
                },
            )
            # Real clock, short explicit fixture window. No retrospective registration.
            time.sleep(max(0, (closes - datetime.now(UTC)).total_seconds()) + 0.05)

            def evidence(title, description):
                return store.put_artifact(
                    case["id"],
                    None,
                    "evidence",
                    title,
                    {
                        "synthetic": True,
                        "description": description,
                    },
                )

            def resolution_body(item, outcome, rationale, previous=None):
                return {
                    "outcome": outcome,
                    "rationale": rationale,
                    "previous_resolution_id": previous,
                    "source_refs": [
                        {
                            "artifact_id": item["id"],
                            "artifact_sha256": item["sha256"],
                            "excerpt": item["content"]["description"],
                            "source_path": "/description",
                        }
                    ],
                }

            preliminary = evidence(
                "Invented TEST preliminary report",
                "Synthetic report: TEST reports 60 protocol-defined responses among "
                "the fixed 100 participants. This is fabricated engineering evidence.",
            )
            resolution_path = f"/api/forecasts/{forecast['id']}/resolutions"
            first_body = resolution_body(
                preliminary,
                "yes",
                "The invented report's 60/100 meets the fixed at-least-50/100 rule.",
            )
            first_key = str(uuid4())
            first = post(resolution_path, first_body, first_key)
            initial = client.get(path).json()["items"]
            initial_score = next(i for i in initial if i["forecast"]["id"] == forecast["id"])
            assert math.isclose(initial_score["assessment"]["brier"], 0.09)
            assert math.isclose(initial_score["assessment"]["improvement"], 0.16)

            correction = evidence(
                "Invented TEST corrected report",
                "Synthetic correction: TEST corrects the response count to 40 among the "
                "same fixed 100 participants, replacing its earlier 60/100 report. "
                "This is fabricated engineering evidence.",
            )
            corrected = post(
                resolution_path,
                resolution_body(
                    correction,
                    "no",
                    "The invented correction replaces the preliminary count; "
                    "40/100 fails the same unchanged threshold. Preserve the earlier adjudication.",
                    first["id"],
                ),
            )
            # Retrying the old operation must not undo its later correction.
            assert post(resolution_path, first_body, first_key)["id"] == first["id"]
            absent = evidence(
                "Invented TEST extension data gap",
                "Synthetic report: no usable TEST extension response count or verified "
                "denominator is available. This fabricated gap does not establish "
                "a negative result.",
            )
            post(
                f"/api/forecasts/{missing['id']}/resolutions",
                resolution_body(
                    absent,
                    "unresolvable",
                    "The invented source lacks the required count and "
                    "denominator, so the fixed fallback rule applies; no Yes/No score is computed.",
                ),
            )
            response = client.get(path)
            assert response.status_code == 200, response.text
            items = response.json()["items"]
            target = next(i for i in items if i["forecast"]["id"] == forecast["id"])
            assert len(target["resolutions"]) == 2
            assert target["latest_resolution"]["id"] == corrected["id"]
            assert math.isclose(target["assessment"]["brier"], 0.49)
            assert math.isclose(target["assessment"]["baseline_brier"], 0.25)
            assert math.isclose(target["assessment"]["improvement"], -0.24)
            assert {i["assessment"]["status"] for i in items} == {
                "resolved",
                "due",
                "pending",
                "abstained",
                "unresolvable",
            }
            assert all(i["forecast"]["content"]["synthetic"] for i in items)
            return {
                "case_id": case["id"],
                "forecast_id": forecast["id"],
                "first_resolution_id": first["id"],
                "correction_id": corrected["id"],
                "pending_id": pending["id"],
                "due_id": due["id"],
                "abstained_id": abstained["id"],
                "unresolvable_id": missing["id"],
                "initial_assessment": initial_score["assessment"],
                "corrected_assessment": target["assessment"],
                "forecast_count": len(items),
                "synthetic": True,
                "model_calls": 0,
                "market_requests": 0,
                "execution_eligible": False,
            }
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    print(json.dumps(seed(parser.parse_args().database_url), indent=2))
