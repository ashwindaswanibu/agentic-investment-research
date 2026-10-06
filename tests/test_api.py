import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from researchdesk.api import create_app
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools
from researchdesk.store import Store


class UnavailableSandbox:
    def availability(self):
        return {"available": False, "reason": "Test has no execution runtime."}


@pytest.fixture
def app_factory(tmp_path):
    stores = []

    def create(**kwargs):
        store = Store(f"sqlite:///{tmp_path}/api-{len(stores)}.db")
        stores.append(store)
        settings = Settings(_env_file=None, **kwargs)
        research = ResearchTools(store, settings, sandbox=UnavailableSandbox())
        return create_app(settings, store, research)

    yield create
    for store in stores:
        store.close()


def create_case(client, key="test-request-0001"):
    return client.post(
        "/api/cases",
        json={"title": "Research case", "hypothesis": "Does the proposed mechanism have evidence?"},
        headers={"Idempotency-Key": key},
    )


def test_auth_cookie_and_bearer_gate_private_research(app_factory):
    app = app_factory(operator_token=SecretStr("local-test-operator"))
    with TestClient(app) as client:
        assert client.get("/api/session").json() == {
            "authenticated": False,
            "authentication_required": True,
        }
        assert client.get("/api/capabilities").status_code == 200
        assert client.get("/api/cases").status_code == 401
        assert client.post("/api/session", json={"token": "wrong"}).status_code == 401
        login = client.post("/api/session", json={"token": "local-test-operator"})
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "local-test-operator" not in login.headers["set-cookie"]
        assert create_case(client).status_code == 201
        client.delete("/api/session")
        assert client.get("/api/cases").status_code == 401
        assert (
            client.get(
                "/api/cases", headers={"Authorization": "Bearer local-test-operator"}
            ).status_code
            == 200
        )


def test_read_only_is_server_enforced(app_factory):
    with TestClient(app_factory(read_only=True)) as client:
        assert client.get("/api/cases").status_code == 200
        assert create_case(client).status_code == 403
        assert (
            client.post(
                "/api/paper/account",
                json={"cash": "10000"},
                headers={"Idempotency-Key": "open-account"},
            ).status_code
            == 403
        )


def test_read_only_inspection_does_not_initialize_paper_control(app_factory):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from researchdesk.db import PaperControlRow

    app = app_factory(read_only=True)
    with TestClient(app) as client:
        response = client.get("/api/paper/operations")
        assert response.status_code == 200
        assert response.json()["control"] == {"version": 0, "mode": "halted", "mandate_id": None}
        assert response.json()["worker"]["active"] is False
        assert client.get("/api/paper/portfolio").json()["initialized"] is False
    with Session(app.state.store.engine) as session:
        assert session.scalar(select(func.count()).select_from(PaperControlRow)) == 0


def test_mutation_rejects_cross_origin_and_oversized_body(app_factory):
    with TestClient(app_factory()) as client:
        response = client.post(
            "/api/cases", json={}, headers={"Origin": "https://attacker.example"}
        )
        assert response.status_code == 403
        assert client.post("/api/cases", content="x" * 2_000_001).status_code == 413


def test_api_idempotency_and_no_canned_agent_fallback(app_factory):
    with TestClient(app_factory()) as client:
        first, again = create_case(client), create_case(client)
        assert first.status_code == 201
        assert first.json()["id"] == again.json()["id"]
        identifier = first.json()["id"]
        run = client.post(
            f"/api/cases/{identifier}/run",
            json={"role": "coordinator"},
            headers={"Idempotency-Key": "run-request-1"},
        )
        assert run.status_code == 409
        assert run.json()["error"]["code"] == "PROVIDER_UNCONFIGURED"
        assert client.get(f"/api/cases/{identifier}").json()["tasks"] == []


def test_operator_cannot_upload_review_or_experiment_or_trust_metadata(app_factory):
    with TestClient(app_factory()) as client:
        identifier = create_case(client).json()["id"]
        path = f"/api/cases/{identifier}/artifacts"
        for kind in ("experiment", "review", "dataset", "paper_intent"):
            assert (
                client.post(
                    path,
                    json={"kind": kind, "title": "Forged", "content": "accepted"},
                    headers={"Idempotency-Key": f"forged-{kind}"},
                ).status_code
                == 422
            )
        note = client.post(
            path,
            json={
                "kind": "note",
                "title": "Comment",
                "content": "human context",
                "metadata": {"execution_eligible": True},
            },
            headers={"Idempotency-Key": "note-upload"},
        ).json()
        assert note["metadata"] == {"operator_supplied": True}
        assert note["task_id"] is None


def test_open_account_is_explicit_and_retry_safe(app_factory):
    with TestClient(app_factory()) as client:
        before = client.get("/api/paper/portfolio").json()
        assert before["initialized"] is False
        headers = {"Idempotency-Key": "account-open"}
        assert (
            client.post("/api/paper/account", json={"cash": "10000"}, headers=headers).status_code
            == 201
        )
        assert (
            client.post("/api/paper/account", json={"cash": "10000"}, headers=headers).status_code
            == 201
        )
        assert (
            client.post("/api/paper/account", json={"cash": "20000"}, headers=headers).status_code
            == 409
        )
        after = client.get("/api/paper/portfolio").json()
        assert after["cash"] == "10000" and len(after["events"]) == 1
