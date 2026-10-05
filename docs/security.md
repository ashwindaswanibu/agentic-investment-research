# Security boundaries

This application is intended for a trusted operator and a separately configured
read-only public viewer. It is not a multi-tenant service for arbitrary users to
submit code. The worker is a privileged component because it controls Docker.

## Execution host

Only the explicit Compose `worker` profile mounts the Docker socket. API and web
images have no socket, and the worker has no published port. Docker daemon access
can grant host-level control; restricting the socket mount to read-only does not
turn the daemon API into a read-only interface. Use a dedicated execution host and
keep its daemon accessible only to trusted operators.
[Docker's daemon security guidance](https://docs.docker.com/engine/security/)
explains this trust boundary.

Generated Python runs in a fresh container using a preinstalled image. It receives
only the supplied code and JSON payload, with no workspace, Docker socket or host
credential mount. The runner disables networking, drops capabilities, disallows
privilege escalation, uses a read-only root filesystem and an unprivileged user,
and limits CPU, memory, processes, writable temporary storage and output. The host
enforces a wall-clock timeout. Missing Docker/image readiness blocks execution.
There is no host-Python fallback. Docker's
[resource controls](https://docs.docker.com/engine/containers/resource_constraints/)
complement isolation; they are not a guarantee against kernel vulnerabilities.

Cancellation removes the active container. Container labels include ownership and
an expiry time so a later worker can clean up after a hard crash. A running worker
performs that cleanup; this is not a separate always-on reaper. A stopped host may
retain expired containers until cleanup resumes. API readiness reads do not invoke
cleanup or other container mutations.

## Model and tool trust

Documents and tool responses are untrusted input, including apparently helpful
instructions embedded in a source. They are delivered as data, never system
instructions. The registry validates requested arguments and checks the task's
stored role. A model cannot grant itself a new tool or permission through prose.
These controls constrain actions; they do not guarantee that a model's financial
reasoning or a cited source is correct.

OpenAI requests go to the official API. The application has no unofficial model
gateway or unauthenticated fallback. Claude CLI, when used locally, handles its
own authentication; the adapter disables host tools, MCP servers, settings and
slash commands. Model output requests only this application's validated tools.
Provider keys are neither copied into generated-code containers nor returned by
the health endpoint. Full live-provider verification is pending authentication in
the initial environment.

Database leases fence stale workers. Tool budgets are consumed atomically and
idempotent writes use deterministic call keys. Independent review binds an exact
artifact hash; subsequent code cannot inherit an earlier version's approval. Paper
accounting accepts no broker credentials and has no live-order path.

## API and publication

External operator binding requires a token. Browser sessions use HTTP-only cookies;
mutation requests validate their origin when supplied. The frontend proxy forwards
the user's session or authorization header and does not inject a privileged token.
The backend enforces read-only mode even when an API request bypasses the UI.
Manual artifact upload is restricted to notes/code and does not accept authoritative
execution metadata. Request sizes and input schemas are bounded.

For a public viewer, use a separate publication database, disable the provider,
remove its credentials, and run no worker. Publish through HTTPS and configure the
exact allowed origins. Existing read-only policy does not redact private artifacts:
review and remove sensitive content before transferring data to a publication
database. Source documents, prompts and tool results may themselves be confidential.

`.env`, database files, local artifacts and logs are excluded from Git and Docker
build context. Generate unique secrets; `.env.example` contains no usable password.
Changing the operator token invalidates existing signed sessions. Avoid posting
`docker compose config` output because it expands environment values; use
`docker compose config --quiet` for validation.

## Verification and limits

CI pins official actions to verified commit IDs with repository read permission,
installs constrained dependencies, audits runtime packages, and runs unit,
PostgreSQL, frontend and real Docker tests. Synthetic fixtures and scripted model
responses are labelled test inputs, not production research. Paid model calls are
not part of unauthenticated CI. Updating pinned actions, images or dependencies
requires running the checks again. This follows GitHub's
[guidance on immutable action references](https://docs.github.com/en/actions/reference/security/secure-use).

Cancellation prevents subsequent writes and tool execution, but an already-sent
OpenAI HTTP request can finish or time out before its client returns. Prefix-only
strategy inputs cannot detect future information deliberately embedded in source
code. Container isolation shares a host kernel and depends on a maintained Docker
host. These limits remain relevant even when the test suite passes.

If a vulnerability is found, provide a minimal reproduction with synthetic data
and no credentials or private source material. Until a private reporting contact
is configured for this repository, do not include sensitive exploit details in a
public issue. This document is a description of implemented controls, not an
independent security certification.
