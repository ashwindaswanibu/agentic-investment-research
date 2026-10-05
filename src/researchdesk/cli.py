"""Local API and durable worker processes with explicit configuration."""

import argparse
import json
import logging
import signal
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn

from researchdesk.agents import Runtime, create_provider, provider_health
from researchdesk.api import create_app, provider_config
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.paper_operations import PaperOperations, quote_provider
from researchdesk.store import Store


def worker(settings: Settings, *, once=False):
    if settings.read_only:
        raise SystemExit("Read-only deployments cannot run workers.")
    configuration = provider_config(settings)
    health = provider_health(configuration)
    if not health["configured"]:
        raise SystemExit(health["reason"])
    store = Store(settings.database_url)
    research = ResearchTools(store, settings)
    stop = threading.Event()
    research.sandbox.cleanup_expired()
    runtime = Runtime(
        store,
        create_provider(configuration),
        research.registry(),
        worker_id=str(uuid4()),
        max_turns=settings.max_turns,
        should_stop=stop.is_set,
    )
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, lambda _signum, _frame: stop.set())

    def heartbeat():
        last_probe = 0.0
        sandbox_health = {"available": False, "reason": "Worker readiness check pending."}
        while not stop.is_set():
            if time.monotonic() - last_probe > 60:
                sandbox_health = research.sandbox.availability()
                last_probe = time.monotonic()
            store.set_system(
                "worker",
                {
                    "last_seen_at": datetime.now(UTC).isoformat(),
                    "epoch": time.time(),
                    "provider": health,
                    "sandbox": sandbox_health,
                },
            )
            stop.wait(5)

    pulse = threading.Thread(target=heartbeat, daemon=True)
    pulse.start()
    try:
        while not stop.is_set():
            try:
                result = runtime.run_once()
                if result:
                    logging.info(
                        "task_finished task_id=%s status=%s", result["id"], result["status"]
                    )
            except Exception:
                # Log identifiers/status in runtime events. Do not dump source text,
                # provider HTTP bodies, or configuration secrets into process logs.
                logging.error("worker_iteration_failed; leases allow recovery")
                result = None
            if once:
                break
            if result is None:
                research.sandbox.cleanup_expired()
                stop.wait(1)
    finally:
        stop.set()
        pulse.join(timeout=6)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        store.close()


def paper_worker(settings: Settings, *, once=False):
    if settings.read_only:
        raise SystemExit("Read-only deployments cannot run paper workers.")
    store = Store(settings.database_url)
    operations = PaperOperations(store, ResearchTools(store, settings), quote_provider(settings))
    worker_id, stop = str(uuid4()), threading.Event()
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, lambda _signum, _frame: stop.set())
    try:
        while not stop.is_set():
            interval = 30
            try:
                result = operations.tick(worker_id)
                logging.info("paper_tick status=%s", result["status"])
                interval = result.get("next_poll_seconds", 5)
            except Exception:
                logging.error("paper_tick_failed; no partial transaction was committed")
            if once:
                break
            stop.wait(interval)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        store.close()


def main():
    parser = argparse.ArgumentParser(
        description="Research Desk: paper-only agentic investment research"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the FastAPI server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    job = sub.add_parser("worker", help="Run a durable research worker")
    job.add_argument("--once", action="store_true")
    paper_job = sub.add_parser(
        "paper-worker", help="Monitor and execute reviewed paper intents within an explicit mandate"
    )
    paper_job.add_argument("--once", action="store_true")
    sub.add_parser("doctor", help="Show nonsecret provider, storage, and sandbox readiness")
    assessment = sub.add_parser(
        "assess-strategy", help="Persist a deterministic assessment of a saved experiment"
    )
    assessment.add_argument("--experiment-id", required=True)
    evaluation = sub.add_parser(
        "evaluate-extraction",
        help="Operator-only comparison of frozen candidate and baseline dossiers",
    )
    evaluation.add_argument("--case-id", required=True)
    evaluation.add_argument("--candidate-id", required=True)
    evaluation.add_argument("--baseline-id", required=True)
    evaluation.add_argument("--reference", type=Path, required=True)
    evaluation.add_argument("--key", required=True, help="Stable unique key for this comparison")
    mechanical = sub.add_parser(
        "evaluate-mechanical", help="Operator-only guided source extraction comparison"
    )
    for name in ("case-id", "candidate-id", "baseline-id", "key"):
        mechanical.add_argument(f"--{name}", required=True)
    for name in ("scope", "reference", "sources"):
        mechanical.add_argument(f"--{name}", type=Path, required=True)
    freeze = sub.add_parser(
        "benchmark-freeze", help="Validate and freeze a versioned source bundle"
    )
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--protocol", type=Path, required=True)
    freeze.add_argument("--blobs", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    pilot = sub.add_parser("benchmark-run", help="Run isolated development pilot attempts")
    pilot.add_argument("--bundle", type=Path, required=True)
    pilot.add_argument("--output", type=Path, required=True)
    pilot.add_argument("--split", choices=["development"], default="development")
    pilot.add_argument("--max-attempts", type=int, default=1)
    report = sub.add_parser(
        "benchmark-report", help="Read all planned and attempted pilot outcomes"
    )
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "serve":
        if args.host not in {"localhost", "127.0.0.1", "::1"} and not (
            settings.read_only or settings.operator_token.get_secret_value()
        ):
            raise SystemExit("External binding requires read-only mode or an operator token.")
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    elif args.command == "worker":
        worker(settings, once=args.once)
    elif args.command == "paper-worker":
        paper_worker(settings, once=args.once)
    elif args.command == "assess-strategy":
        from researchdesk.domain import artifact_ref
        from researchdesk.quant.assessment import assess_saved_experiment

        if settings.read_only:
            raise SystemExit("Read-only deployments cannot persist assessments.")
        store = Store(settings.database_url)
        try:
            print(json.dumps(artifact_ref(assess_saved_experiment(store, args.experiment_id))))
        finally:
            store.close()
    elif args.command.startswith("benchmark-"):
        from researchdesk.research.benchmark_bundle import freeze_bundle
        from researchdesk.research.benchmark_runner import report, run_suite

        try:
            if args.command == "benchmark-freeze":
                if settings.read_only:
                    raise ValueError("Read-only deployments cannot create benchmark bundles")
                result = freeze_bundle(
                    manifest_path=args.manifest,
                    protocol_path=args.protocol,
                    blobs=args.blobs,
                    output=args.output,
                )
            elif args.command == "benchmark-run":
                result = run_suite(
                    bundle_path=args.bundle,
                    output=args.output,
                    split=args.split,
                    settings=settings,
                    max_attempts=args.max_attempts,
                )
            else:
                result = report(args.output)
        except (ValueError, OSError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2))
    elif args.command == "evaluate-mechanical":
        from researchdesk.mechanical_workflow import evaluate_mechanical_comparison
        from researchdesk.research.benchmark_bundle import read_json

        if settings.read_only:
            raise SystemExit("Read-only deployments cannot record evaluations.")
        scope = read_json(args.scope, maximum=200_000)
        reference = read_json(args.reference, maximum=500_000)
        sources = read_json(args.sources, maximum=20_000)
        store = Store(settings.database_url)
        try:
            result = evaluate_mechanical_comparison(
                store,
                candidate_id=args.candidate_id,
                baseline_id=args.baseline_id,
                scope=scope,
                reference=reference,
                source_bindings=sources,
                case_id=args.case_id,
                key=args.key,
            )
            print(
                json.dumps(
                    {"id": result["id"], "sha256": result["sha256"], "content": result["content"]},
                    indent=2,
                )
            )
        finally:
            store.close()
    elif args.command == "evaluate-extraction":
        from researchdesk.quality_workflow import evaluate_extraction

        if settings.read_only:
            raise SystemExit("Read-only deployments cannot record evaluations.")
        if args.reference.stat().st_size > 2_000_000:
            raise SystemExit("Reference file exceeds the 2 MB evaluation limit.")
        store = Store(settings.database_url)
        try:
            result = evaluate_extraction(
                store,
                candidate_id=args.candidate_id,
                baseline_id=args.baseline_id,
                reference=json.loads(args.reference.read_text()),
                case_id=args.case_id,
                key=args.key,
            )
            print(
                json.dumps(
                    {"id": result["id"], "sha256": result["sha256"], "content": result["content"]},
                    indent=2,
                )
            )
        finally:
            store.close()
    else:
        store = Store(settings.database_url)
        try:
            print(
                json.dumps(
                    {
                        "provider": provider_health(provider_config(settings)),
                        "sandbox": ResearchTools(store, settings).sandbox.availability(),
                        "database": store.engine.dialect.name,
                        "read_only": settings.read_only,
                        "execution_mode": "paper",
                    },
                    indent=2,
                )
            )
        finally:
            store.close()


if __name__ == "__main__":
    main()
