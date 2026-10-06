"""Build or serve two finite synthetic walkthroughs, with no external services.

Run from the repository after installing its development dependencies:
    python examples/public_demo.py build --output /path/to/NEW_DIRECTORY
    python examples/public_demo.py serve --directory /path/to/PACKAGE

The database contains invented evidence and real workflow records, not a model
run, calibrated forecast, execution result, or investment recommendation.
"""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from researchdesk.api import create_app
from researchdesk.config import Settings
from researchdesk.db import Base
from researchdesk.domain import ResearchTools
from researchdesk.store import Store, content_hash

SCHEMA_VERSION = 1
DATABASE = "researchdesk.db"
MANIFEST = "manifest.json"
NOTICE = (
    "Entirely synthetic engineering fixtures. Prices, probabilities, study evidence and "
    "outcomes are invented; timestamps and the short forecast event window use the real clock. "
    "No model run, market data request, calibrated forecast, paper trade or investment result. "
    "Fresh builds have different IDs, timestamps and hashes."
)
EXPECTED_KINDS = {
    "note": 1,
    "hypothesis": 2,
    "options_chain": 1,
    "instrument_comparison": 1,
    "evidence": 4,
    "forecast": 5,
    "forecast_resolution": 3,
}
EMPTY_TABLES = {
    "research_tasks",
    "research_tool_calls",
    "paper_accounts",
    "paper_ledger",
    "paper_mandates",
    "paper_observations",
    "paper_market_sessions",
    "system_state",
}


class PackageError(ValueError):
    """The directory is not an intact, finite public-demo package."""


class DemoSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # Omitting a field still uses its code default; no environment, .env or
        # secret directory participates, including fields added to Settings later.
        return (init_settings,)


def isolated_settings(directory, *, read_only):
    return DemoSettings(
        database_url=f"sqlite:///{directory / DATABASE}",
        artifact_dir=directory / "disabled-artifacts",
        read_only=read_only,
        provider="disabled",
        retrieval_mode="lexical",
        _env_file=None,
    )


class ReadOnlyStore(Store):
    def __init__(self, database):
        # Keep native Store queries without schema creation or make_engine's
        # writable WAL setup. Only finalized packages that remain unchanged
        # while served are supported; verification also rejects sidecars.
        uri = database.as_uri() + "?mode=ro&immutable=1"
        self.engine = create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False),
            poolclass=NullPool,
        )


class DisabledSandbox:
    def availability(self):
        return {"available": False, "reason": "Execution is disabled in this public demo."}


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise PackageError(message)


def _inventory(database):
    """Validate the whole tiny package, not a capped library result or an export."""
    uri = database.as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        require(
            connection.execute("PRAGMA quick_check").fetchall() == [("ok",)],
            "Database integrity check failed.",
        )
        schema = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        require(
            not any(kind in {"trigger", "view"} for kind, _ in schema),
            "Unexpected database views or triggers.",
        )
        tables = {name for kind, name in schema if kind == "table"}
        require(tables == set(Base.metadata.tables), "Unexpected database schema.")
        require(
            not connection.execute("PRAGMA foreign_key_check").fetchall(),
            "Database has broken references.",
        )
        counts = {
            name: connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name in sorted(tables)
        }
        require(
            all(counts[name] == 0 for name in EMPTY_TABLES),
            "Demo contains task, worker or paper-operation data.",
        )
        require(
            counts["research_cases"] == 2 and counts["research_artifacts"] == 17,
            "Expected exactly two cases and seventeen artifacts.",
        )
        # The forecast API initializes a dormant control row, never an account.
        connection.row_factory = sqlite3.Row
        controls = connection.execute("SELECT * FROM paper_control").fetchall()
        require(
            len(controls) == 1
            and dict(controls[0])
            == {
                "id": "paper-main",
                "version": 0,
                "mode": "halted",
                "mandate_id": None,
                "worker_id": None,
                "lease_until": None,
                "fence": 0,
                "last_seen_at": None,
                "latest_tick": None,
                "peak_equity": None,
                "drawdown_tripped": 0,
            },
            "Paper controls are not the pristine dormant fixture.",
        )

    store = ReadOnlyStore(database)
    try:
        cases = sorted(store.list_cases(), key=lambda item: item["id"])
        artifacts = sorted(store.list_artifacts(), key=lambda item: item["id"])
        by_id = {artifact["id"]: artifact for artifact in artifacts}
        case_ids = {case["id"] for case in cases}
        require(
            Counter(a["kind"] for a in artifacts) == EXPECTED_KINDS,
            "Unexpected artifact inventory.",
        )
        require(
            all(
                "synthetic" in case["title"]
                and case["status"] == "draft"
                and not case["tool_calls_used"]
                for case in cases
            ),
            "Cases are not the expected synthetic fixtures.",
        )

        def reference(identifier, owner, digest=None):
            target = by_id.get(identifier)
            require(
                target is not None and target["case_id"] == owner["case_id"],
                "Artifact lineage leaves its synthetic case.",
            )
            require(
                digest is None or target["sha256"] == digest,
                "Artifact lineage hash does not match.",
            )

        def lineage(value, owner):
            if isinstance(value, list):
                for child in value:
                    lineage(child, owner)
            elif isinstance(value, dict):
                if "id" in value and "sha256" in value:
                    reference(value["id"], owner, value["sha256"])
                if "artifact_id" in value:
                    reference(value["artifact_id"], owner, value.get("artifact_sha256"))
                for key, child in value.items():
                    if key in {"source_artifact_ids", "scenario_source_ids"}:
                        for identifier in child:
                            reference(identifier, owner)
                    elif (
                        key
                        in {
                            "hypothesis_id",
                            "chain_artifact_id",
                            "forecast_id",
                            "previous_resolution_id",
                        }
                        and child
                    ):
                        reference(child, owner)
                    lineage(child, owner)

        for artifact in artifacts:
            content = artifact["content"]
            require(
                artifact["case_id"] in case_ids and artifact["task_id"] is None,
                "Unexpected artifact ownership.",
            )
            require(
                isinstance(content, dict) and content.get("synthetic") is True,
                "Every artifact must be explicitly synthetic.",
            )
            require(content_hash(content) == artifact["sha256"], "Artifact hash mismatch.")
            lineage(content, artifact)
            lineage(artifact["metadata"], artifact)
        events = store.list_events(limit=100)
        require(len(events) == counts["research_events"] == 19, "Unexpected event inventory.")
        require(
            all(
                event["kind"] in {"case.created", "artifact.created"}
                and event["case_id"] in case_ids
                and event["task_id"] is None
                for event in events
            ),
            "Unexpected task or paper events.",
        )
        return {
            "table_counts": counts,
            "artifact_counts": dict(sorted(EXPECTED_KINDS.items())),
            "cases": [
                {
                    "id": case["id"],
                    "title": case["title"],
                    "description": case["hypothesis"],
                    "sha256": content_hash(case),
                }
                for case in cases
            ],
            "artifacts": [
                {
                    "id": artifact["id"],
                    "case_id": artifact["case_id"],
                    "kind": artifact["kind"],
                    "sha256": artifact["sha256"],
                }
                for artifact in artifacts
            ],
        }
    finally:
        store.close()


def _walkthroughs(inventory):
    by_kind = {item["kind"]: item["case_id"] for item in inventory["artifacts"]}
    return [
        {
            "id": "instruments",
            "title": "A bullish thesis can still buy an expensive option",
            "description": "Inspect invented prices, conditional payoffs and a missing quote. "
            "Compare cash, stock, a call and a spread under the same assumptions.",
            "href": f"/cases/{by_kind['instrument_comparison']}?tab=research",
        },
        {
            "id": "forecasts",
            "title": "A forecast, a resolution and a correction",
            "description": "Inspect five invented forecasts, retained source evidence and "
            "a correction that changes the score while preserving history.",
            "href": f"/cases/{by_kind['forecast']}?tab=forecasts",
        },
    ]


def build_package(output):
    output = Path(output).absolute()
    # mkdir is exclusive, including dangling symlinks. No reset/overwrite option.
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise PackageError("Output already exists; choose a new directory.") from exc
    output = output.resolve()
    settings = isolated_settings(output, read_only=False)
    # Support both direct script invocation and import by the test suite.
    if __package__:
        from .forecast_lifecycle_verification import seed as seed_forecasts
        from .instrument_comparison_verification import seed as seed_instruments
    else:
        from forecast_lifecycle_verification import seed as seed_forecasts
        from instrument_comparison_verification import seed as seed_instruments
    seed_instruments(settings.database_url, settings=settings)
    seed_forecasts(settings.database_url, settings=settings)
    database = output / DATABASE
    require(
        set(path.name for path in output.iterdir()) == {DATABASE},
        "Database must be closed with no WAL, SHM or extra files before packaging.",
    )
    inventory = _inventory(database)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "built_at": datetime.now(UTC).isoformat(),
        "fixture_notice": NOTICE,
        "external_requests": 0,
        "model_calls": 0,
        "execution_eligible": False,
        "database": {
            "path": DATABASE,
            "sha256": file_hash(database),
            "bytes": database.stat().st_size,
        },
        "inventory": inventory,
        "walkthroughs": _walkthroughs(inventory),
    }
    with (output / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return manifest


def verify_package(directory):
    directory = Path(directory).absolute()
    require(
        not directory.is_symlink() and directory.is_dir(),
        "Package must be a real directory, not a symlink.",
    )
    require(
        set(path.name for path in directory.iterdir()) == {DATABASE, MANIFEST},
        "Package must contain only its database and manifest; reject WAL/SHM sidecars.",
    )
    require(
        all(not path.is_symlink() and path.is_file() for path in directory.iterdir()),
        "Package files must be regular files, not symlinks.",
    )
    directory = directory.resolve()
    try:
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        require(
            manifest["schema_version"] == SCHEMA_VERSION
            and manifest["synthetic"] is True
            and manifest["fixture_notice"] == NOTICE
            and manifest["external_requests"] == manifest["model_calls"] == 0
            and manifest["execution_eligible"] is False,
            "Unsupported or malformed demo manifest.",
        )
        require(
            datetime.fromisoformat(manifest["built_at"]).utcoffset() is not None,
            "Build timestamp must have a timezone.",
        )
        database = directory / DATABASE
        require(
            manifest["database"]
            == {
                "path": DATABASE,
                "sha256": file_hash(database),
                "bytes": database.stat().st_size,
            },
            "Database file hash or size does not match the manifest.",
        )
        inventory = _inventory(database)
        require(manifest["inventory"] == inventory, "Manifest inventory does not match database.")
        require(
            manifest["walkthroughs"] == _walkthroughs(inventory),
            "Walkthrough paths do not match the synthetic cases.",
        )
        return manifest
    except (KeyError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
        if isinstance(exc, PackageError):
            raise
        raise PackageError("Malformed demo package.") from exc


def create_viewer(directory):
    manifest = verify_package(directory)
    directory = Path(directory).resolve()
    settings = isolated_settings(directory, read_only=True)
    store = ReadOnlyStore(directory / DATABASE)
    try:
        research = ResearchTools(store, settings, sandbox=DisabledSandbox())
        app = create_app(settings=settings, store=store, research=research)
    except Exception:
        store.close()
        raise
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original_lifespan(app):
                yield
        finally:
            store.close()

    app.router.lifespan_context = lifespan

    @app.get("/api/demo")
    def demo():
        return {
            key: manifest[key]
            for key in ("schema_version", "synthetic", "built_at", "walkthroughs")
        }

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Create a new synthetic package (about six seconds).")
    build.add_argument("--output", required=True, type=Path)
    serve = commands.add_parser("serve", help="Verify and serve a package with the read-only API.")
    serve.add_argument("--directory", required=True, type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8011, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(json.dumps(build_package(args.output), indent=2, ensure_ascii=False))
        else:
            import uvicorn

            uvicorn.run(create_viewer(args.directory), host=args.host, port=args.port)
    except (PackageError, OSError) as exc:
        parser.exit(2, f"Public demo: {exc}\n")


if __name__ == "__main__":
    main()
