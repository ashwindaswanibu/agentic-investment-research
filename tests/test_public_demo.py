"""Finite synthetic demo: real workflow fixtures, no outbound calls or user data."""

import importlib.util
import json
import shutil
import socket
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[1]
CANARY = "public-demo-secret-canary-DO-NOT-RETAIN"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = tmp_path_factory.mktemp("public-demo")
    existing = root / "operator.db"
    existing.write_bytes(b"existing operator database must never be opened or changed")
    original = existing.read_bytes()
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "examples"))
        spec = importlib.util.spec_from_file_location(
            "public_demo", ROOT / "examples/public_demo.py"
        )
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        patch.chdir(root)
        (root / ".env").write_text(
            "RESEARCHDESK_PROVIDER=not-a-provider\n"
            "RESEARCHDESK_READ_ONLY=not-a-boolean\n"
            f"RESEARCHDESK_OPERATOR_TOKEN={CANARY}\n"
            f"RESEARCHDESK_DATABASE_URL=sqlite:///{existing}\n",
            encoding="utf-8",
        )
        values = {
            "DATABASE_URL": f"sqlite:///{existing}",
            "PROVIDER": "openai",
            "MODEL": CANARY,
            "OPENAI_API_KEY": CANARY,
            "ALPACA_API_KEY": CANARY,
            "ALPACA_SECRET_KEY": CANARY,
            "TRADIER_SANDBOX_TOKEN": CANARY,
            "OPERATOR_TOKEN": CANARY,
            "READ_ONLY": "true",
            "RETRIEVAL_MODE": "dense",
            "ARTIFACT_DIR": str(root / "operator-artifacts"),
            "DOCKER_BINARY": CANARY,
            "CLAUDE_BINARY": CANARY,
            "ALLOWED_ORIGINS": "https://operator.invalid",
        }
        for key, value in values.items():
            patch.setenv(f"RESEARCHDESK_{key}", value)
        original_connect = socket.socket.connect

        def no_outbound(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                assert address[0] in {"127.0.0.1", "::1", "localhost"}, address
            return original_connect(self, address)

        def no_process(*args, **kwargs):
            pytest.fail("Demo must not invoke Docker, providers or a background process.")

        patch.setattr(socket.socket, "connect", no_outbound)
        patch.setattr(subprocess, "Popen", no_process)
        package = root / "package"
        manifest = builder.build_package(package)
        assert existing.read_bytes() == original
        assert not (root / "operator-artifacts").exists()
        yield builder, package, manifest
        assert existing.read_bytes() == original


def test_package_is_finite_synthetic_and_isolated(demo):
    builder, package, manifest = demo
    assert builder.verify_package(package) == manifest
    assert set(path.name for path in package.iterdir()) == {"manifest.json", "researchdesk.db"}
    assert manifest["schema_version"] == 1 and manifest["synthetic"] is True
    assert manifest["external_requests"] == manifest["model_calls"] == 0
    assert manifest["execution_eligible"] is False
    assert len(manifest["inventory"]["cases"]) == 2
    assert len(manifest["inventory"]["artifacts"]) == 17
    assert all(manifest["inventory"]["table_counts"][key] == 0 for key in builder.EMPTY_TABLES)
    assert manifest["inventory"]["artifact_counts"] == builder.EXPECTED_KINDS
    for path in package.iterdir():
        assert CANARY.encode() not in path.read_bytes()
    settings = builder.isolated_settings(package, read_only=True)
    assert settings.provider == "disabled" and settings.retrieval_mode == "lexical"
    assert settings.read_only and settings.model == ""
    for key in (
        "openai_api_key",
        "alpaca_api_key",
        "alpaca_secret_key",
        "tradier_sandbox_token",
        "operator_token",
    ):
        assert getattr(settings, key).get_secret_value() == ""


def test_real_read_only_api_has_demo_navigation_and_rejects_mutations(demo):
    builder, package, manifest = demo
    before = builder.file_hash(package / builder.DATABASE)
    app = builder.create_viewer(package)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        descriptor = client.get("/api/demo").json()
        assert set(descriptor) == {"schema_version", "synthetic", "built_at", "walkthroughs"}
        assert descriptor["walkthroughs"] == manifest["walkthroughs"]
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["read_only"] is True
        assert capabilities["authentication_required"] is False
        assert capabilities["provider"]["configured"] is False
        assert capabilities["sandbox"]["available"] is False
        assert capabilities["worker"]["active"] is False
        assert capabilities["retrieval"] == {"mode": "lexical", "model": None}
        cases = client.get("/api/cases").json()["items"]
        assert len(cases) == 2
        for case in cases:
            detail = client.get(f"/api/cases/{case['id']}").json()
            assert not detail["tasks"] and not detail["tool_calls"]
            assert all(artifact["content"]["synthetic"] for artifact in detail["artifacts"])
        assert client.get("/api/library?q=synthetic").status_code == 200
        assert client.get("/api/paper/operations").json()["control"]["mode"] == "halted"
        assert client.get("/api/paper/performance").status_code == 200
        for path, body in [
            ("/api/cases", {"title": "Attempted mutation", "hypothesis": "Must be rejected."}),
            (f"/api/cases/{cases[0]['id']}/run", {}),
            ("/api/paper/account", {"cash": "10000"}),
        ]:
            response = client.post(path, json=body, headers={"Idempotency-Key": "demo-denied-123"})
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "READ_ONLY"
        # The database itself refuses writes even if the API boundary is bypassed.
        with pytest.raises(OperationalError, match="readonly"):
            app.state.store.create_case("Rejected", "Database is physically read only.")
    assert builder.file_hash(package / builder.DATABASE) == before
    assert builder.verify_package(package) == manifest


def test_forecast_fixture_preserves_real_window_and_correction(demo):
    builder, package, manifest = demo
    app = builder.create_viewer(package)
    forecast_case = next(
        item["href"].split("/")[2].split("?")[0]
        for item in manifest["walkthroughs"]
        if item["id"] == "forecasts"
    )
    with TestClient(app) as client:
        items = client.get(f"/api/cases/{forecast_case}/forecasts").json()["items"]
    assert len(items) == 5
    assert {item["assessment"]["status"] for item in items} == {
        "resolved",
        "unresolvable",
        "due",
        "pending",
        "abstained",
    }
    corrected = next(item for item in items if len(item["resolutions"]) == 2)
    forecast = corrected["forecast"]["content"]
    assert (
        datetime.fromisoformat(forecast["registered_at"])
        < datetime.fromisoformat(forecast["opens_at"])
        < datetime.fromisoformat(forecast["closes_at"])
    )
    for resolution in corrected["resolutions"]:
        assert datetime.fromisoformat(resolution["content"]["recorded_at"]) >= (
            datetime.fromisoformat(forecast["closes_at"])
        )
    assert corrected["assessment"]["brier"] == pytest.approx(0.49)
    assert corrected["assessment"]["improvement"] == pytest.approx(-0.24)


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling-symlink"])
def test_build_refuses_existing_output_without_mutation(demo, tmp_path, kind):
    builder, package, _ = demo
    output = tmp_path / "do-not-overwrite"
    if kind == "directory":
        output.mkdir()
        (output / "sentinel").write_text(CANARY)
    elif kind == "file":
        output.write_text(CANARY)
    else:
        output.symlink_to(package if kind == "symlink" else tmp_path / "missing")
    before = builder.file_hash(package / builder.DATABASE)
    with pytest.raises(builder.PackageError, match="already exists"):
        builder.build_package(output)
    assert output.is_symlink() or output.exists()
    if kind == "directory":
        assert (output / "sentinel").read_text() == CANARY
    elif kind == "file":
        assert output.read_text() == CANARY
    assert builder.file_hash(package / builder.DATABASE) == before


@pytest.mark.parametrize(
    "change",
    [
        "database",
        "manifest",
        "path",
        "sidecar",
        "symlink",
        "package-symlink",
        "inventory",
        "lineage",
    ],
)
def test_viewer_refuses_tampered_or_malformed_package(demo, tmp_path, change):
    builder, package, _ = demo
    copied = tmp_path / "modified"
    shutil.copytree(package, copied)
    manifest_path = copied / builder.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    if change == "database":
        with (copied / builder.DATABASE).open("ab") as stream:
            stream.write(b"tampered")
    elif change == "manifest":
        manifest_path.write_text("{")
    elif change == "path":
        manifest["database"]["path"] = "../operator.db"
        manifest_path.write_text(json.dumps(manifest))
    elif change == "sidecar":
        (copied / f"{builder.DATABASE}-wal").write_bytes(b"")
    elif change == "symlink":
        (copied / builder.DATABASE).unlink()
        (copied / builder.DATABASE).symlink_to(package / builder.DATABASE)
    elif change == "package-symlink":
        copied = tmp_path / "linked"
        copied.symlink_to(package)
    else:
        with sqlite3.connect(copied / builder.DATABASE) as connection:
            if change == "inventory":
                connection.execute("DELETE FROM research_events WHERE seq = 1")
            else:
                row = connection.execute(
                    "SELECT id, content FROM research_artifacts WHERE kind = 'hypothesis' LIMIT 1"
                ).fetchone()
                content = json.loads(row[1])
                content["source_artifact_ids"] = ["unrelated-user-artifact"]
                connection.execute(
                    "UPDATE research_artifacts SET content = ?, sha256 = ? WHERE id = ?",
                    (json.dumps(content), builder.content_hash(content), row[0]),
                )
        # Even a rewritten file digest cannot conceal invalid lineage/inventory.
        manifest["database"]["sha256"] = builder.file_hash(copied / builder.DATABASE)
        manifest["database"]["bytes"] = (copied / builder.DATABASE).stat().st_size
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(builder.PackageError):
        builder.create_viewer(copied)


def test_cli_defaults_and_output_contains_no_environment_credentials(demo, monkeypatch, capsys):
    builder, package, manifest = demo
    monkeypatch.setattr(builder, "build_package", lambda output: manifest)
    builder.main(["build", "--output", "new-directory"])
    assert CANARY not in capsys.readouterr().out
    calls = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    builder.main(["serve", "--directory", str(package)])
    assert calls[0][1] == {"host": "127.0.0.1", "port": 8011}
    assert calls[0][0].state.settings.read_only
    calls[0][0].state.store.close()
