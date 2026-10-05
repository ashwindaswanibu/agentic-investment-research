"""Operator API and a genuinely read-only public research viewer."""

import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr

from researchdesk import __version__
from researchdesk.agents import ProviderConfig, provider_health, register_delegation
from researchdesk.config import Settings
from researchdesk.domain import Input, ResearchTools
from researchdesk.errors import DomainError
from researchdesk.paper import PaperError, Quote
from researchdesk.paper_operations import (
    ControlInput,
    MandateInput,
    PaperOperations,
    quote_provider,
)
from researchdesk.quant import QuantError
from researchdesk.service import PaperService
from researchdesk.store import WORKSPACES, Store


class CaseInput(Input):
    title: str = Field(min_length=1, max_length=200)
    hypothesis: str = Field(min_length=5, max_length=12000)
    workspace_id: str = "general"
    tool_budget: int = Field(default=40, ge=1, le=200)


class RunInput(Input):
    role: Literal["coordinator"] = "coordinator"


class ManualArtifact(Input):
    kind: Literal["note", "code"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)
    metadata: dict = Field(default_factory=dict)


class SessionInput(Input):
    token: SecretStr


class AccountInput(Input):
    cash: Decimal = Field(default=Decimal("10000"), gt=0, le=Decimal("10000000"))


class OrderInput(Input):
    intent_id: str
    quotes: dict[str, Quote] = Field(max_length=100)


class FillInput(Input):
    quotes: dict[str, Quote] = Field(max_length=100)


def provider_config(settings):
    return ProviderConfig(
        provider=settings.provider,
        model=settings.model,
        api_key=settings.openai_api_key.get_secret_value(),
        timeout_seconds=settings.provider_timeout_seconds,
        claude_binary=settings.claude_binary,
    )


def public_task(task):
    return {
        k: v
        for k, v in task.items()
        if k not in {"messages", "checkpoint", "worker_id", "lease_until"}
    }


def create_app(settings=None, store=None, research=None):
    settings = settings or Settings()
    owned_store = store is None
    store = store or Store(settings.database_url)
    research = research or ResearchTools(store, settings)
    paper = PaperService(store, research)
    operations = PaperOperations(store, research, quote_provider(settings))

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned_store:
            store.close()

    app = FastAPI(title="Research Desk", version=__version__, lifespan=lifespan)
    app.state.store, app.state.research, app.state.settings = store, research, settings
    secret = settings.operator_token.get_secret_value()

    def effective_provider():
        worker = store.get_system("worker") or {}
        if time.time() - worker.get("epoch", 0) < 30 and worker.get("provider"):
            return worker["provider"]
        return provider_health(provider_config(settings))

    def signature(value):
        return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()

    def authenticated(request):
        if not secret:
            return True
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], secret):
            return True
        cookie = request.cookies.get("researchdesk_session", "")
        parts = cookie.split(".")
        if len(parts) != 2 or not parts[0].isdigit():
            return False
        return int(parts[0]) > time.time() and secrets.compare_digest(parts[1], signature(parts[0]))

    def access(request: Request):
        if not authenticated(request):
            raise DomainError("AUTH_REQUIRED", "Sign in with the configured operator token.", 401)

    def mutate(request: Request):
        access(request)
        if settings.read_only:
            raise DomainError("READ_ONLY", "This deployment is a read-only research viewer.", 403)

    def request_key(idempotency_key: str = Header(alias="Idempotency-Key")):
        if not 8 <= len(idempotency_key) <= 180:
            raise DomainError(
                "INVALID_REQUEST_KEY", "Supply an Idempotency-Key between 8 and 180 characters."
            )
        return idempotency_key

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in settings.allowed_origins.split(","):
                return JSONResponse(
                    {"error": {"code": "ORIGIN_DENIED", "message": "Origin is not allowed."}}, 403
                )
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                length = 2_000_001
            if length > 2_000_000:
                return JSONResponse(
                    {
                        "error": {
                            "code": "BODY_TOO_LARGE",
                            "message": "Request exceeds the size limit.",
                        }
                    },
                    413,
                )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "BODY_TOO_LARGE",
                                "message": "Request exceeds the size limit.",
                            }
                        },
                        413,
                    )
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"error": exc.as_dict()}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request fields do not match the API schema.",
                    "fields": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()],
                }
            },
            422,
        )

    @app.exception_handler(PaperError)
    @app.exception_handler(QuantError)
    async def calculation_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, 409)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # No exception strings: upstream URLs or model SDKs may carry secrets.
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The operation failed; no successful result was recorded.",
                }
            },
            500,
        )

    @app.get("/api/health")
    def health():
        store.get_system("worker")
        return {"status": "ok", "version": __version__, "database": "connected"}

    @app.get("/api/session")
    def session(request: Request):
        return {"authenticated": authenticated(request), "authentication_required": bool(secret)}

    @app.post("/api/session")
    def login(body: SessionInput, request: Request, response: Response):
        if secret and not secrets.compare_digest(body.token.get_secret_value(), secret):
            raise DomainError("INVALID_TOKEN", "The operator token is incorrect.", 401)
        expires = str(int(time.time()) + 8 * 3600)
        response.set_cookie(
            "researchdesk_session",
            expires + "." + signature(expires),
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=8 * 3600,
        )
        return {"authenticated": True, "authentication_required": bool(secret)}

    @app.delete("/api/session")
    def logout(response: Response):
        response.delete_cookie("researchdesk_session", httponly=True, samesite="strict")
        return {"authenticated": not bool(secret), "authentication_required": bool(secret)}

    @app.get("/api/capabilities")
    def capabilities(request: Request):
        worker = store.get_system("worker") or {}
        return {
            "execution_mode": "paper",
            "read_only": settings.read_only,
            "authenticated": authenticated(request),
            "authentication_required": bool(secret),
            "provider": effective_provider(),
            "sandbox": worker["sandbox"]
            if time.time() - worker.get("epoch", 0) < 30 and worker.get("sandbox")
            else research.sandbox.availability(),
            "worker": {
                "last_seen_at": worker.get("last_seen_at"),
                "active": time.time() - worker.get("epoch", 0) < 30,
            },
            "retrieval": {
                "mode": settings.retrieval_mode,
                "model": settings.embedding_model if settings.retrieval_mode == "dense" else None,
            },
            "tools": register_delegation(research.registry()).describe(),
            "limitations": [
                "Paper execution only; no broker connection or live orders.",
                "Daily-bar backtests reject dividend/split intervals; fixed "
                "fee and slippage assumptions.",
                "Walk-forward selects from a declared SMA family; it does not "
                "establish investable alpha.",
                "Paper fills require explicit, current attributable quotes and "
                "deterministic risk admission.",
            ],
        }

    read = [Depends(access)]
    write = [Depends(mutate)]

    @app.get("/api/workspaces", dependencies=read)
    def workspaces():
        return {"items": WORKSPACES}

    @app.get("/api/cases", dependencies=read)
    def cases():
        return {"items": store.list_cases()}

    @app.post("/api/cases", dependencies=write, status_code=201)
    def create_case(body: CaseInput, key=Depends(request_key)):
        return store.create_case(**body.model_dump(), idempotency_key="case:" + key)

    @app.get("/api/cases/{case_id}", dependencies=read)
    def case_detail(case_id: str):
        return {
            **store.get_case(case_id),
            "tasks": [public_task(t) for t in store.list_tasks(case_id)],
            "artifacts": store.list_artifacts(case_id),
            "tool_calls": store.list_tool_calls(case_id=case_id),
            "events": store.list_events(case_id),
        }

    @app.post("/api/cases/{case_id}/run", dependencies=write, status_code=202)
    def run_case(case_id: str, body: RunInput, key=Depends(request_key)):
        if not effective_provider()["configured"]:
            raise DomainError(
                "PROVIDER_UNCONFIGURED",
                "Authenticate a model provider before launching agents.",
                409,
            )
        case = store.get_case(case_id)
        guidance = ""
        if case["workspace_id"] == "clinical":
            from researchdesk.research.quality import CLINICAL_DOSSIER_GUIDANCE

            guidance = "\n\n" + CLINICAL_DOSSIER_GUIDANCE
        task = store.create_task(
            case_id,
            body.role,
            "Investigate the case hypothesis. Delegate specialist research and coding, "
            "inspect their artifacts, and commission independent review. Revise when "
            "evidence requires it. Use the persisted tools for all claims and calculations. "
            "Record the hypothesis and its falsification rule before experiments. "
            "Retain revisions and rejections. If domain expertise or a reusable tool is missing, "
            "delegate a researcher to write its specification and evidence standards, a coder "
            "to implement the tool, and an independent reviewer to test it. Activate specialists "
            "only through the registry. Finish with supported findings and unresolved questions."
            + guidance
            + "\n\n"
            + case["hypothesis"],
            idempotency_key="run:" + case_id + ":" + key,
        )
        return {"case_id": case_id, "task_id": task["id"], "status": task["status"]}

    @app.post("/api/cases/{case_id}/cancel", dependencies=write)
    def cancel_case(case_id: str):
        return store.cancel_case(case_id)

    @app.get("/api/tasks", dependencies=read)
    def tasks(case_id: str | None = None):
        return {"items": [public_task(t) for t in store.list_tasks(case_id)]}

    @app.get("/api/tasks/{task_id}", dependencies=read)
    def task_detail(task_id: str):
        task = store.get_task(task_id)
        return {
            **public_task(task),
            "tool_calls": store.list_tool_calls(task_id),
            "artifacts": [
                a for a in store.list_artifacts(task["case_id"]) if a["task_id"] == task_id
            ],
        }

    @app.get("/api/artifacts", dependencies=read)
    def artifacts(case_id: str | None = None, kind: str | None = None):
        return {"items": store.list_artifacts(case_id, kind)}

    @app.get("/api/artifacts/{artifact_id}", dependencies=read)
    def artifact(artifact_id: str):
        return store.get_artifact(artifact_id)

    @app.post("/api/cases/{case_id}/artifacts", dependencies=write, status_code=201)
    def create_artifact(case_id: str, body: ManualArtifact, key=Depends(request_key)):
        return store.put_artifact(
            case_id,
            None,
            body.kind,
            body.title,
            body.content,
            {"operator_supplied": True},
            idempotency_key="artifact:" + case_id + ":" + key,
        )

    @app.get("/api/experiments", dependencies=read)
    def experiments():
        return {"items": store.list_artifacts(kind="experiment")}

    @app.get("/api/experiments/{artifact_id}", dependencies=read)
    def experiment(artifact_id: str):
        return research.artifact(artifact_id, kind="experiment")

    @app.get("/api/library", dependencies=read)
    def library(q: str = ""):
        if not q.strip():
            return {"items": store.list_artifacts(), "mode": settings.retrieval_mode}
        if len(q) > 2000:
            raise DomainError("QUERY_TOO_LONG", "Search query is too long.")
        return research.search(q, 20)

    @app.get("/api/events", dependencies=read)
    def events(case_id: str | None = None, after: int = 0):
        items = store.list_events(case_id, max(0, after))
        return {"items": items, "cursor": items[-1]["seq"] if items else after}

    @app.get("/api/paper/portfolio", dependencies=read)
    def portfolio():
        return paper.portfolio()

    @app.get("/api/paper/operations", dependencies=read)
    def paper_operations():
        return operations.status()

    @app.get("/api/paper/performance", dependencies=read)
    def paper_performance():
        return operations.performance()

    @app.post("/api/paper/mandates", dependencies=write, status_code=201)
    def paper_mandate(body: MandateInput, key=Depends(request_key)):
        return operations.create_mandate(body, "mandate:" + key)

    @app.post("/api/paper/operations/control", dependencies=write)
    def paper_control(body: ControlInput):
        return operations.set_control(body)

    @app.post("/api/paper/account", dependencies=write, status_code=201)
    def open_account(body: AccountInput, key=Depends(request_key)):
        return {"events": paper.open_account(body.cash, "paper:" + key)}

    @app.post("/api/paper/orders", dependencies=write, status_code=201)
    def order(body: OrderInput, key=Depends(request_key)):
        return {"events": paper.reserve(body.intent_id, body.quotes, "paper:" + key)}

    @app.post("/api/paper/orders/{order_id}/fill", dependencies=write)
    def fill(order_id: str, body: FillInput, key=Depends(request_key)):
        return {"events": paper.fill(order_id, body.quotes, "paper:" + key)}

    @app.post("/api/paper/orders/{order_id}/cancel", dependencies=write)
    def cancel_order(order_id: str, key=Depends(request_key)):
        return {"events": paper.cancel(order_id, "paper:" + key)}

    return app
