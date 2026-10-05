# Running Research Desk

The default configuration is a read-only viewer with no model provider. Agent runs
need an authenticated provider and a running worker. Generated Python additionally
needs Docker and the sandbox image. There is no canned-response or host-execution
fallback.

Use Python 3.12, Node.js 24, and a running Docker engine. The frontend lockfile and
`requirements.lock` constrain the tested dependencies. Commands below run from the
repository root unless stated otherwise.

## Native local development

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -c requirements.lock '.[dev,retrieval]'
cp .env.example .env
```

Generate local secrets without printing them or adding them to Git:

```sh
python - <<'PY'
from pathlib import Path
import secrets

path = Path('.env')
text = path.read_text()
for name in ('POSTGRES_PASSWORD', 'RESEARCHDESK_OPERATOR_TOKEN'):
    text = text.replace(name + '=\n', name + '=' + secrets.token_hex(32) + '\n')
path.write_text(text)
path.chmod(0o600)
PY
```

Edit `.env` locally. For an operator session set
`RESEARCHDESK_READ_ONLY=false`. Choose one provider:

| Provider | Required local configuration |
| --- | --- |
| OpenAI | `RESEARCHDESK_PROVIDER=openai`, an available model ID in `RESEARCHDESK_MODEL`, and `RESEARCHDESK_OPENAI_API_KEY` |
| Claude CLI | Install the supported Claude CLI, run `claude auth login`, and set `RESEARCHDESK_PROVIDER=claude_cli`; optionally select a model and binary path |

OpenAI uses the official Responses endpoint and function-call/result protocol.
Claude CLI uses its own authentication and a structured application-tool protocol;
its built-in host tools, MCP servers, settings and slash commands are disabled.
The application never extracts CLI credentials. The provided container worker uses
OpenAI; it does not bundle Claude CLI or mount a personal authentication directory.

```sh
docker build -f deploy/sandbox.Dockerfile -t researchdesk-sandbox:local .
researchdesk doctor
researchdesk serve
```

In another terminal, activate the same virtual environment and start the worker:

```sh
. .venv/bin/activate
researchdesk worker
```

In a third terminal:

```sh
cd web
npm ci
npm run dev
```

Open `http://127.0.0.1:3000` and sign in with the operator token from your local
`.env`. The frontend forwards requests to `http://127.0.0.1:8010` through its own
`/api` routes. Its server-only `RESEARCH_API_URL` can select a different backend.
Never put model keys or the operator token in `NEXT_PUBLIC_*` variables.

SQLite is the default for a local API and one worker. For PostgreSQL, start the
optional database with `docker compose up -d db`, then set the native process's
`RESEARCHDESK_DATABASE_URL` to
`postgresql+psycopg://researchdesk:<password>@127.0.0.1:5432/researchdesk`.
Use the port configured by `POSTGRES_PORT` if changed. Hexadecimal passwords from
the setup command need no URL escaping.

## Containers

`compose.yaml` runs PostgreSQL, the API and the standalone Next.js frontend.
Ports bind to loopback. PostgreSQL has no default password: `.env` must provide
`POSTGRES_PASSWORD`. The API image runs without Docker or a Docker socket.

```sh
docker compose config --quiet
docker compose build api web
docker compose up -d db api web
docker compose ps
```

To enable agent execution, configure OpenAI, an operator token, and
`RESEARCHDESK_READ_ONLY=false` in `.env`. Build the sandbox on the same daemon used
by the worker, then explicitly enable the worker profile:

```sh
docker build -f deploy/sandbox.Dockerfile -t researchdesk-sandbox:local .
docker compose --profile worker build worker
docker compose --profile worker up -d worker
docker compose logs --tail=100 worker
```

The worker profile mounts the Docker socket and runs with daemon-level authority.
Run it only on a trusted operator machine or dedicated execution host. It has no
published HTTP port. Neither the web service nor the API mounts the socket. The
worker publishes provider and sandbox readiness for the API to display.
Container embedding caches use `/tmp/researchdesk-artifacts/embeddings` on writable
temporary storage; authoritative artifacts remain in PostgreSQL. The cache is
rebuildable and is discarded when a container is replaced.

For Docker Desktop installations without `/var/run/docker.sock`, set
`DOCKER_SOCKET_PATH` to the actual local socket in `.env`. Do not use an
unauthenticated TCP Docker endpoint. Compose must use the same daemon on which
the sandbox image was built.

The worker can be stopped without cancelling the research case:

```sh
docker compose --profile worker stop worker
```

It yields interrupted tasks with their checkpoints intact. Starting a worker
again resumes queued work. A hard crash is recovered after the task lease expires;
worker cleanup removes expired containers carrying this application's ownership
and deadline labels. OpenAI HTTP requests may finish or time out after a stop or
cancellation; revoked leases prevent subsequent tool execution and writes.

## Public viewer

Use a separate publication database containing only approved artifacts. Set
`RESEARCHDESK_READ_ONLY=true`, `RESEARCHDESK_PROVIDER=disabled`, and leave the model
key empty. Do not enable the worker profile. A public viewer must not share an
execution worker or a live operator database.

Keep the Compose ports on loopback and put an HTTPS reverse proxy in front of the
web service. Set both `RESEARCH_ALLOWED_ORIGINS` and
`RESEARCHDESK_ALLOWED_ORIGINS` to the exact public origin. Set the operator token
only if the viewer should require authentication. The API rejects mutation
requests in read-only mode; hiding frontend buttons is not its security boundary.

Do not publish proprietary source material, full restricted market datasets,
private prompts, credentials or unreviewed tool arguments/results. Local smoke
artifacts are ignored by Git and are not a licensed public dataset.

## Verification

```sh
ruff check src tests examples
ruff format --check src tests examples
pytest -q -m 'not live and not sandbox and not integration'
RESEARCHDESK_SANDBOX_IMAGE=researchdesk-sandbox:local \
  pytest -q tests/test_sandbox.py tests/test_domain.py -m sandbox
python -m pip_audit -r requirements.lock --no-deps --disable-pip
```

For real PostgreSQL concurrency tests, set `RESEARCHDESK_TEST_DATABASE_URL` to a
disposable PostgreSQL database and run
`pytest -q tests/test_postgres.py tests/test_paper_operations_postgres.py`. The user
must be able to create schemas. Tests create and remove only uniquely named test
schemas. Do not aim integration tests at a production database.

```sh
cd web
npm ci
npm run typecheck
npm test
npm run build
npm audit --omit=dev --audit-level=high
```

GitHub CI uses Python 3.12, Node 24, PostgreSQL 17, the same sandbox image definition,
and commit-pinned official actions. CI has no model credentials and does not run
paid live inference. Unit tests explicitly use synthetic data or scripted provider
fixtures; Docker and PostgreSQL tests exercise real services.

As of the initial implementation, actual Docker, PostgreSQL, public-data retrieval,
and local embedding checks have run. **A complete live LLM-driven research run has
not been verified because no model provider was authenticated.** Configured means
credentials/session presence, not proven inference access. After authenticating,
run a small case and inspect its retained calls, artifacts, review, and terminal
status. The opt-in Claude protocol smoke is
`RESEARCHDESK_LIVE_CLAUDE=1 pytest -q tests/test_agent_providers.py -m live`.

## Backups and troubleshooting

Back up PostgreSQL and test restores before upgrading. This release creates its
schema on startup; it does not ship a production migration system. Record the
application revision, pinned dependencies, image digest and configuration with a
backup. For local SQLite, stop API and worker before copying the database and its
associated journal files. `docker compose down` keeps the named database volume;
adding `--volumes` deletes that stored data.

Use `/api/health` for database connectivity and `/api/capabilities` for provider,
worker, sandbox and read-only state. A stale worker heartbeat means no live worker
has recently advertised readiness. Missing isolation blocks Python execution;
missing model authentication blocks agent launch. Dense retrieval must be enabled
explicitly and may download its public embedding model on first use; it never
silently becomes lexical retrieval. `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` prevents
automatic use of an ambient Hugging Face login for public model downloads.

Paper monitoring uses a separate worker without model credentials or a Docker
socket. See [the paper operations contract](paper-operations.md) for explicit
mandates, modes, data configuration and performance semantics.
