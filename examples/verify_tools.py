"""Run actual acquisition, sandbox execution and evaluation without a model key.

This is an explicitly labelled tool integration run, never a staged agent run.
No reviewer or paper decision is fabricated. Supply your own interval/symbol;
unsupported corporate actions fail instead of silently distorting returns.
"""

import argparse
from pathlib import Path
from uuid import uuid4

from researchdesk.agents import ToolContext
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument(
        "--generated", action="store_true", help="Also execute isolated Python per session"
    )
    args = parser.parse_args()
    settings = Settings()
    if settings.read_only:
        raise SystemExit("Tool verification writes artifacts; use a local operator environment.")
    store = Store(settings.database_url)
    research = ResearchTools(store, settings)
    registry = research.registry()
    case = store.create_case(
        f"Tool verification · {args.symbol} · {args.start}",
        "Direct integration verification using actual market data and deterministic tools. "
        "This is not an autonomous model run or evidence of an investment edge.",
        workspace_id="quantitative",
    )
    task = store.create_task(case["id"], "coder", case["hypothesis"])
    worker_id = "verification-" + str(uuid4())
    store.claim_task(worker_id, lease_seconds=3600, task_id=task["id"])

    def call(name, arguments):
        call_id = str(uuid4())
        record = store.begin_tool_call(task["id"], call_id, name, arguments, worker_id=worker_id)
        context = ToolContext(
            store,
            case["id"],
            task["id"],
            call_id,
            worker_id,
            lambda: store.is_cancelled(task["id"]),
        )
        result = registry.execute(name, arguments, context)
        store.finish_tool_call(
            record["id"],
            "completed" if result["ok"] else "failed",
            result=result,
            error=result.get("error"),
            worker_id=worker_id,
        )
        if not result["ok"]:
            raise RuntimeError(f"{result['error']['code']}: {result['error']['message']}")
        return result["data"]

    try:
        dataset = call(
            "acquire_market_data", {"symbol": args.symbol, "start": args.start, "end": args.end}
        )
        experiment = call("run_experiment", {"dataset_id": dataset["id"], "mode": "backtest"})
        artifacts = [dataset["id"], experiment["id"]]
        if args.generated:
            code = call(
                "write_artifact",
                {
                    "kind": "code",
                    "title": "Volatility-scaled trend policy",
                    "content": Path(__file__).with_name("volatility_trend.py").read_text(),
                },
            )
            generated = call(
                "run_experiment",
                {"dataset_id": dataset["id"], "mode": "generated_strategy", "code_id": code["id"]},
            )
            artifacts.extend([code["id"], generated["id"]])
        store.update_task(
            task["id"],
            worker_id=worker_id,
            status="completed",
            summary="Direct tool verification completed with retained inputs and computations. "
            "No autonomous model run or strategy-performance claim.",
            result={"artifact_ids": artifacts, "verification_mode": "direct_tools"},
        )
        print(f"Inspect the retained verification: http://127.0.0.1:3000/cases/{case['id']}")
    except Exception as exc:
        store.update_task(
            task["id"],
            worker_id=worker_id,
            status="failed",
            error={"code": "VERIFICATION_FAILED", "message": str(exc)},
        )
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
