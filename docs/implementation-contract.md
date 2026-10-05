# Implementation contract

This is the shared development contract, not a claim that capabilities are complete.

## Product

A case-centered investment research workbench: a persistent specialist workspace
originates and investigates hypotheses, delegates bounded tasks, creates versioned
code/data artifacts, evaluates experiments, obtains review, and proposes paper
decisions. Research is not restricted to filings. The first two example workflows
are quantitative strategy development and source-backed clinical evidence research.
Every displayed result comes from persisted work. Test fixtures are explicitly
labeled; no production provider returns canned research.

The old implementation remains untouched. This clean repository replaces the
incorrect execution/evaluation core while retaining useful design lessons.

## Ownership

- Root: package/configuration, database/store, FastAPI routes, domain tools and
  data/retrieval, worker integration, deployment, end-to-end validation, publication.
- Runtime agent: `src/researchdesk/agents/`, `src/researchdesk/sandbox.py`, related
  tests. Actual provider/tool loop, delegation, recovery, review/artifact binding.
- Quant agent: `src/researchdesk/quant/`, `src/researchdesk/paper/`, related tests.
  Validated datasets, real numerical backtest/walk-forward/scenario calculations,
  deterministic paper risk and replayable ledger.
- Frontend agent: `web/` and frontend tests. Next.js/React/TypeScript, real API
  contracts, accessible responsive research/experiment/portfolio/library views.

## Runtime and dependencies

Python >=3.12, FastAPI/Pydantic v2, synchronous SQLAlchemy 2 store (short independent
transactions), HTTPX, NumPy. SQLite local single-worker mode; PostgreSQL deployment
mode with durable leases. React/Next.js on Node >=22. No live brokerage client.
Generated Python executes only in a resource-limited, network-disabled Docker
container. Missing isolation is a blocked operation, never host execution fallback.
Use official provider documentation. OpenAI Responses supports tool call/result
continuations; Anthropic/other adapters can be added behind the same protocol.

## Shared store contract (root implements)

Resources are JSON-serializable dictionaries; dates are UTC ISO8601; identifiers
are UUID strings; errors have stable codes and human-readable messages. Money is
serialized as decimal strings. All write methods commit before returning.

`Store(database_url)` exposes:

- `create_case(title, hypothesis, workspace_id='general', tool_budget=40,
  idempotency_key=None) -> dict`
- `get_case(case_id) -> dict`; `list_cases() -> list[dict]`
- `update_case(case_id, **fields) -> dict` (status, summary only)
- `create_task(case_id, role, instruction, parent_id=None, artifact_ids=None,
  idempotency_key=None) -> dict`
- `get_task(task_id) -> dict`; `list_tasks(case_id=None) -> list[dict]`
- `claim_task(worker_id, lease_seconds=120) -> dict | None` (queued or expired
  lease); `renew_lease(task_id, worker_id, lease_seconds=120) -> bool`
- `update_task(task_id, **fields) -> dict` (status, checkpoint, result, error,
  summary; expected lease ownership supplied where applicable)
- `cancel_case(case_id) -> dict` (terminalize queued children, flag running tasks)
- `append_event(case_id, kind, data, task_id=None) -> dict`
- `list_events(case_id=None, after=0, limit=200) -> list[dict]` (global monotonic seq)
- `consume_budget(case_id, amount=1) -> bool` (atomic shared case budget)
- `put_artifact(case_id, task_id, kind, title, content, metadata=None,
  idempotency_key=None) -> dict` (immutable content hash)
- `get_artifact(artifact_id) -> dict`; `list_artifacts(case_id=None, kind=None)`
- `begin_tool_call(task_id, call_id, name, arguments) -> dict` (unique task+call_id;
  repeat returns prior state/result)
- `finish_tool_call(tool_id, status, result=None, error=None) -> dict`
- `list_tool_calls(task_id=None, case_id=None) -> list[dict]`
- `save_messages(task_id, messages) -> None`; `get_messages(task_id) -> list[dict]`

`checkpoint` holds provider-native continuation and pending call IDs. Root store
can add small helpers on request; coordinate contracts before using absent methods.
Tool handlers that mutate artifacts use deterministic idempotency keys from their
tool call IDs. Interrupted external reads may retry; committed side effects must
deduplicate. Do not claim global exactly-once external execution.

## Resource fields

Case: `id,title,hypothesis,workspace_id,status,summary,tool_budget,tool_calls_used,
created_at,updated_at`. Status: `draft,queued,running,waiting,completed,failed,cancelled`.

Task: `id,case_id,parent_id,role,instruction,status,artifact_ids,attempt,checkpoint,
result,error,summary,created_at,started_at,finished_at,lease_until`.
Status: `queued,running,waiting,completed,failed,blocked,cancelled`.
Roles: `researcher,coder,reviewer,coordinator`.

Artifact: `id,case_id,task_id,kind,title,content,sha256,metadata,created_at`.
Core kinds: `evidence,dataset,code,experiment,review,note,paper_intent`.
Research kinds: `hypothesis,clinical_dossier,specialist_spec,specialist_activation,
research_tool_spec,research_tool_tests,research_tool_qualification,research_tool_result`.
Operator-only evaluation kinds: `evaluation_reference,evaluation_report`; these
are excluded from model reads, retrieval, code inputs and delegation.
Content may be a string or structured JSON. Metadata identifies sources, as-of
times, producing versions, and exact input artifact IDs/hashes.

ToolCall: `id,task_id,call_id,name,arguments,status,result,error,duration_ms,
started_at,finished_at`. Status: `running,completed,failed,blocked`.

Event: `seq,case_id,task_id,kind,data,created_at`.

An experiment is an artifact of kind `experiment`; its content contains
`status,spec,metrics,equity_curve,folds,trades,validation` where applicable.
Its metadata binds dataset/code hashes. Review content includes
`verdict,findings,artifact_id,artifact_sha256,experiment_ids`; root validates the
reviewer task is not the producer and the referenced hashes exist.

## HTTP API (root implements)

All paths below are `/api`. Errors use `{error:{code,message}}` and appropriate
HTTP status. List endpoints return `{items:[...]}`. Details return the object.
Mutation requests accept an `Idempotency-Key` header. No secret goes into a
`NEXT_PUBLIC_*` variable or rendered artifact. Public-read-only mode rejects all
mutations server-side; local operator mode binds loopback by default.

- `GET /health`: `{status,version,database}`
- `GET /capabilities`: `{execution_mode:'paper',read_only,provider:{name,model,
  configured},sandbox:{available,reason},worker:{last_seen_at,active},tools:[...],
  limitations:[...]}`
- `GET /workspaces`: `{items:[{id,name,description}]}`
- `GET /cases`; `POST /cases` body `{title,hypothesis,workspace_id,tool_budget}`
- `GET /cases/{id}`: case fields plus `tasks,artifacts,tool_calls,events`
- `POST /cases/{id}/run` body `{role:'coordinator'}` -> 202 `{case_id,task_id,status}`
- `POST /cases/{id}/cancel` -> case
- `GET /tasks`; `GET /tasks/{id}` -> task plus `tool_calls,artifacts`
- `GET /artifacts?case_id=&kind=`; `GET /artifacts/{id}`
- `POST /cases/{id}/artifacts` body `{kind,title,content,metadata}` -> artifact
- `GET /experiments` -> experiment artifacts; `GET /experiments/{id}` -> artifact
- `GET /library?q=` -> `{items:[artifact with score]}` (actual retrieval)
- `GET /events?case_id=&after=` -> `{items:[...],cursor:number}`; polling is a
  valid first integration; resumable SSE can be added without changing semantics.
- `GET /paper/portfolio` -> `{account_id,cash,equity,realized_pnl,positions,events,
  currency:'USD',execution_mode:'paper'}` (Decimal strings)
- `POST /paper/orders` -> accepts explicit paper intent only after validated
  artifact/review and deterministic cash/exposure checks; exact contract follows.

## Tool registry boundary

Each tool has a Pydantic input schema, description, allowed roles, side-effect
category, and sync handler. Runtime validates calls, enforces role permissions and
shared budgets, persists call start/result, returns typed errors to the model.
Core tools: evidence retrieval, market-data snapshots, library search, artifact
creation/read, delegation, quantitative experiment, sandboxed Python, review,
paper proposal. A tool result is `{ok:bool,data?:any,error?:{code,message}}`.
External evidence is untrusted data; source text is never appended as privileged
instructions. Completion prose cannot bypass experiment/review/ledger gates.

## Quality gates

- Hand-checked accounting and no-lookahead tests, real next-session fills.
- Durable recovery, cancellation, shared budgets, idempotent committed effects.
- Exact artifact/version review binding and failed/rejected cases retained.
- Container execution has no network/host secrets, has CPU/memory/process/output
  limits, and cancellation removes the running container.
- Real provider smoke run (when configured), no secret logging or canned fallback.
- API/frontend integration, browser visual/interaction review, dependency scan,
  fresh install/run documentation and CI. Read-only public demo cannot spend funds.
- Resume names only capabilities verified in this implementation and clearly
  identifies development/test results rather than investment-performance claims.
