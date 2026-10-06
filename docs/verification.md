# Verification record

## Full LEAN tick-input attempt, 2026-10-06 UTC

- Pinned LEAN source and .NET SDK compiled the real C# launcher and isolated
  comparison algorithm in GitHub Actions. No QuantConnect account, CLI or market
  subscription was used. Runtime networking was disabled.
- All eight scenarios were attempted and retained, but native initialization
  rejected option Tick resolution in every case. Each native result reports
  RuntimeError and zero orders. There is no verified fill, expiry, assignment or
  terminal accounting result from this attempt.
- 38 local fixture and runner tests passed. They cover native file generation,
  input provenance, incomplete/failed observations and continuation after errors;
  they do not establish the engine's lifecycle correctness.
- Independent review confirmed the supported-resolution restriction and the
  need for separately declared minute-bar controls. The original inputs and
  failure evidence remain intact; no model or subscription bypass was introduced.

See the [protocol and observed result](decisions/lean-runtime-protocol.md#first-execution-native-tick-input-rejected)
and [actual CI run](https://github.com/ashwindaswanibu/agentic-investment-research/actions/runs/37411363545).
Options engine selection and admission remain unfinished.

## Combined demo container, 2026-10-05

[GitHub Actions run 37408081344](https://github.com/ashwindaswanibu/agentic-investment-research/actions/runs/37408081344)
passed all four jobs on source commit `1f0303dfe52b1bdb0ca13769a54a647fdfce5f86`.
The new job built the actual Python/Next image from a fresh Linux amd64 checkout,
including the synthetic database. The pinned images supplied Python 3.12.15 and
Node 24.21.0. No local runtime or operator database was copied.

The combined container ran as UID/GID 10001 with a 512 MiB memory limit, no extra
swap, 0.1 CPU quota, read-only root, 64 MiB temporary storage and no Linux
capabilities. First proxied API readiness took **50.72 seconds**; cgroup peak memory
was **188,768,256 bytes (180.02 MiB)**, with no OOM events. These measurements cover
the declared finite workload on that runner, not a general capacity or latency SLA.

The [retained receipt](https://github.com/ashwindaswanibu/agentic-investment-research/actions/runs/37408081344/artifacts/11388640242)
records image ID `sha256:0f9fc6057f9d1160af7646927aff0ffc8eadf92bb7fe8ca24d3776f581d50d13`
and 13 completed checks:

- Both walkthrough pages and case APIs, five forecast records, library search,
  paper halt state, disabled capabilities and 12 actual JS/CSS assets loaded.
- API writes returned the backend's `READ_ONLY` error. File permissions rejected
  write access; the application's immutable SQLite URI allowed reading and refused
  a CREATE statement. The database hash remained unchanged.
- Graceful SIGTERM exited within the bound. Killing either the Python API or Next
  process separately caused the supervisor to stop the container with an error.
  A malformed manifest failed before frontend startup.
- The supervisor has 27 new subprocess/health tests. The complete Python job passed
  1,329 offline tests (three inapplicable parameter cases skipped), plus 11 actual
  PostgreSQL tests. Frontend and sandbox jobs passed their existing 138 and six tests;
  dependency audits reported no known vulnerabilities at the time of the run.

Independent review found and corrected a failure-test bug: Next rewrites its
process title, so the checker now identifies the supervisor's direct children by
executable. The first container run also exposed a test assumption about SQLite
WAL error wording. The revised check first proves reading through the application's
URI and tests filesystem write access separately; protection was not relaxed.

The [Render configuration](../render.yaml) selects free compute and disables
automatic deployment. The image is qualified for this bounded demo workload;
**Render account access, hosting billing review and an actual public HTTPS
deployment remain pending**. CI hardening flags are not claims about Render's
runtime settings. Real agent research, Tradier authentication, options lifecycle
qualification and sustained operation remain separate unfinished gates.

## Public repository and remote CI, 2026-10-05

The source is public at
[ashwindaswanibu/agentic-investment-research](https://github.com/ashwindaswanibu/agentic-investment-research).
The [first GitHub Actions run](https://github.com/ashwindaswanibu/agentic-investment-research/actions/runs/37406193773)
completed successfully on source commit `e1eaf73de6ea2c418d9f805b97848c2db9cd80ae`.
It used fresh Ubuntu runners with Python 3.12 and Node 24:

- **Python:** constrained installation, Ruff lint/format, 1,302 offline tests,
  then 11 tests against actual PostgreSQL covering concurrency and recovery.
  The offline matrix skipped three inapplicable timestamp/location combinations
  and deselected 24 declared service-dependent tests; the skips are not missing
  PostgreSQL checks. The existing Starlette/httpx warning remains.
- **Sandbox:** built the pinned execution image, asserted Docker readiness and
  passed six actual container isolation, cancellation, recovery and generated-policy
  tests. The other 55 tests in those files were deselected for this specific job.
- **Frontend:** fresh `npm ci`, typecheck, 138 tests and a production build passed.
- **Dependency audits:** Python's locked dependency audit and the frontend
  production dependency audit reported no known vulnerabilities at run time.

The final publication review caught and fixed a fresh-checkout setup bug: the demo
builder now creates the missing parent of `artifacts/public-demo` while continuing
to reject an existing output directory. Its 16 focused tests passed. The exact
README build command then succeeded from a `git archive` with no `artifacts/`
directory, retaining two cases and 17 synthetic artifacts. That additional local
replay reused the installed Python environment; remote CI supplied the fresh
dependency installations.

These results establish the stated engineering checks, not investment performance
or autonomous research quality. HTTPS demo hosting, a genuine model-driven
research demonstration, authenticated Tradier verification, options lifecycle
qualification and sustained operation remain unfinished. Earlier entries below
describe the state at their respective milestones.

## Isolated demonstration package, 2026-10-05

The [guided demo](public-demo.md) now builds its own finite synthetic database
and serves it through the application with a read-only SQLite connection. No
operator data or credentials are copied. This qualifies a local engineering
walkthrough, not an authenticated agent run or a public deployment.

- 1,302 offline Python tests passed; three inapplicable parameter combinations skipped,
  24 live/sandbox/integration cases deselected. The existing Starlette/httpx
  deprecation warning remains. The demo's 16 tests include conflicting environment
  and dotenv credentials, outbound-network/process denial, modified packages,
  source lineage, overwrite refusal and API/database write rejection.
- 138 frontend tests passed, as did TypeScript and the production build. A final
  read-only presentation adjustment passed 22 targeted tests and another build.
  Ruff lint/format and whitespace checks passed. Independent review ran 61 focused
  demo/API/paper-operation tests and found no blocker within the documented scope.
- A clean copy of all 245 source files rebuilt two cases and 17 synthetic artifacts
  with zero provider requests. This reused the installed Python dependencies;
  it was not a fresh dependency-install or hosted-container qualification.
- Browser inspection followed both entry-page links into computed comparisons
  and corrected forecast scores, checked the read-only state and the 390-pixel
  layout. The comparison still shows its missing ask as unavailable; forecast
  history retains the correction and the resulting 0.49 versus 0.25 Brier errors.
- A bounded audit of 237 tracked files, 11 existing commits and 353 historical
  blobs found no tracked environment files (apart from examples), local databases,
  private-key headers, OpenAI-key patterns or local user paths. This pattern audit
  is not exhaustive secret certification. New demo files contain synthetic inputs
  and code only; generated databases and receipts remain ignored.

During this work, read-only API startup was changed to avoid initializing paper
control state. An empty viewer reports a halted, unfunded account without writing
operating records. Ordinary operator initialization retains its previous behavior.
Manifest hashes establish local integrity, not signed provenance. Package files
must remain unchanged while the immutable viewer runs.

At this milestone, publication and remote CI were still pending; the subsequent
checkpoint above records their completion. HTTPS hosting, a real model-driven
research demonstration, Tradier authentication and investment usefulness remain
unverified. No resume performance claims were added.

## Earlier verification

Local verification on October 5, 2026 covered the following boundaries. These
checks establish engineering behavior within the stated scope; they are not
investment-performance results.

| Area | Execution and evidence |
| --- | --- |
| Market experiments | Acquired 81 real TSLA sessions, executed built-in and isolated generated policies, and retained actual calls, data, code and results. The case is explicitly labelled direct tool verification, not autonomous model research. |
| Source connectors | Actual ClinicalTrials.gov, PubMed and market-data requests succeeded with retained provenance. |
| Retrieval | Real BGE model retrieval succeeded, including a repeat query reusing cached vectors inside the deployed API container. |
| Generated tools | A generated arithmetic tool passed independently specified examples and was invoked in real Docker containers. This checks execution and promotion boundaries, not scientific usefulness. |
| Database | PostgreSQL 17.11 integration tests exercised concurrency, leases, cancellation and rollback. SQLite covers local execution. |
| Deployment | An isolated Compose deployment built backend/frontend images, served HTML and static assets, reached PostgreSQL, and passed authentication, read-only mutation rejection and origin checks. Containers ran nonroot; the API had no Docker socket, Docker executable or model credentials. Temporary deployment resources were removed. |
| Research quality | Deterministic tests cover source integrity, quotations, trial/claim links, abstention consistency, extraction scoring and label isolation. All gold fixtures used by these tests are explicitly synthetic. |
| Specialists | Scripted-provider tests exercise reviewed profile creation, delegation, tool restrictions and resume behavior. They are orchestration tests, not real model-quality measurements. |

Run the checks documented in [operations](operations.md) and the repository CI
workflow to reproduce the corresponding engineering tests. Network source checks
depend on the providers' current availability. Integration tests require their
declared disposable services; no test should quietly substitute fake production
research for an unavailable dependency.

The real model-driven research workflow still needs validation with an
authenticated provider. No independently labelled real-world benchmark score,
prospective forecast record, autonomous trading result or remote CI result is
claimed by this verification record.

## Paper operations milestone, 2026-10-05

The staged engineering method and remaining component gates are recorded in
[the roadmap](engineering-roadmap.md); this milestone does not qualify the full
investment system.

- 420 Python tests passed with external integration, sandbox and live-provider
  tests excluded. New cases include strict quote/calendar boundaries, hand-derived
  P&L, mandate controls, reviewed-intent admission, liquidity reuse, close scheduling,
  missing baselines, same-tick drawdown and rollback. Test market inputs are synthetic.
- Four additional tests passed against actual PostgreSQL 17.11 in disposable
  schemas: competing claims, competing control changes, a halt during quote fetch,
  and failure after ledger flush followed by a single successful retry.
- 52 frontend tests, TypeScript and a production build passed. An actual isolated
  API response passed the production frontend parser. Browser review verified the
  empty main state and mandate form, then a separate explicitly synthetic account:
  active → exit only → halted controls, unchanged held positions, stale valuations,
  missing P&L baselines, chart gaps and failure messages. Duplicate rounded chart
  labels were corrected and visually rechecked. Temporary QA services were stopped;
  no synthetic mandates or valuations were added to the main account.
- Independent review identified and reproduced Decimal-spelling liquidity reuse,
  drawdown-latch bypass, missed close windows, incompatible closing freshness and
  truncated baseline issues. Fixes have regression coverage. Drawdown is also
  rechecked after each accepted fill before subsequent entries.
- Ruff lint/format and diff whitespace checks passed. CI now includes the new
  PostgreSQL operations tests; remote CI has not run because publication is pending.

The local app starts with no saved/active mandate, no market credentials and no
paper worker heartbeat. This is an honest unconfigured state. The authenticated
Alpaca smoke is unrun; no brokerage orders, live-feed trading record, or investment
performance result is claimed. Source calendar completeness is an explicit provider
assumption with retained query coverage and change detection.

The optional paper-worker container was also executed against temporary SQLite
inside a network-disabled, read-only-rootfs container. It ran as UID/GID 10001,
without Docker or market/model credentials, recorded `data_blocked` with
`FEED_UNCONFIGURED`, and produced zero ledger events/observations. Read-only mode
exited before creating its test database. The disposable container and temporary
image were removed. Compose configuration validation passed without exposing secrets.

## M1 reproducibility foundation, 2026-10-05

The [pilot runner](benchmark-runner.md) now provides frozen manifests/source
bundles, isolated attempt stores, a complete case/arm/repetition matrix and a
shared model-call journal around the actual application runtime. Final holdout
execution is closed. This milestone establishes engineering behavior, not model
quality or the success of adaptive research.

- **555 Python tests passed**, with 19 external integration/sandbox/live checks
  deselected. The one warning is the existing upstream Starlette/httpx deprecation.
  Ruff lint/format and diff whitespace checks passed. No frontend code changed.
- Independent review reproduced and fixed symlinked bundle paths, recovery-time
  deadline misclassification, unbound effective provider timeouts, incomplete
  usage reporting and overly permissive output permissions.
- Tests exercise the real Runtime/MeteredProvider persistence boundary: crash
  after a cached response but before conversation checkpoint; crash with a request
  in flight; lease expiry and resume; and crash before final journal commit.
  Scripted model fixtures are explicitly synthetic. A returned response is reused
  without another provider call; an unknown outcome is not silently retried.
- Actual source acquisition retained 11 successful raw responses, including six
  evidence blobs for three clinical families. All six imported through the real
  runner preparation path into three isolated temporary SQLite stores with exact
  hashes, mapped artifact identities and idempotent repeat import. No labels,
  projections or cross-case evidence were imported. Temporary stores were removed.
- Numeric, boolean and null JSON-pointer attribution is implemented and tested.
  These checks establish retained source-value presence, not claim entailment.
- The [options spike](decisions/options-engine-spike.md) executed six scenarios
  through pinned Nautilus 2.0.0rc6 in a separate environment. Funded exercise and
  worthless expiry matched independent arithmetic. Funding errors, missing/stale
  settlement data and unstable lifecycle IDs remain adoption blockers. LEAN
  container metadata was inspected; its runtime has not been executed.

Real clinical cases remain unlabelled and unscored. The current extraction schema
cannot faithfully represent some source/analysis/population distinctions; the
[reference contract decision](decisions/0003-clinical-reference-scope.md) records
the next required work. No real provider-driven benchmark, independently
adjudicated quality gain, authenticated market operation or public deployment
was completed by this milestone. The new local runner is SQLite/single-process;
it does not claim a distributed or PostgreSQL benchmark execution path.

## M1 source-qualified output and inspection, 2026-10-05

The [v2 output design](research/clinical-observation-design.md) now preserves
source/analysis contexts, population counts, endpoint links and reconciliation.
It retains explicit unresolved, not-applicable, null and scoped missing-key states.
Production submission and all three benchmark arms use bounded source navigation;
legacy dossiers remain readable and the legacy scorer rejects v2.

- **761 Python tests passed** with external integration/sandbox/live checks excluded.
  **Four real-source integration tests** passed separately against the pinned local
  acquisition package. Those tests explicitly skip without the package rather
  than substituting invented sources. Ruff lint/format and diff whitespace passed.
- Independent adversarial review produced 94 validator cases and found four gaps:
  asymmetric endpoint links, overly broad group contexts, false absence receiving
  attribution credit, and null/zero masquerading as false availability. Fixes bind
  reciprocal links, exact owning containers and exact count/boolean source values.
  Global budgets include anchors and absence proofs. JSON-pointer whitespace is
  preserved rather than silently normalized.
- The [direct-tool script](../examples/clinical_observation_verification.py)
  imported all six exact source blobs into an isolated database. Real registered
  tools retained Vertex's distinct enrolled/dosed/safety/endpoint populations and
  outcome-local group IDs. DCVax retained original randomized assignment and the
  external comparison from the same publication as separate contexts, alongside
  unresolved prespecification and scoped registry-key absence.
- Final local evidence is under
  `artifacts/clinical-observation-verification-20261005T152400Z-ce1006/`:
  `verification-report.json`, `verification.db` and the two readable dossier
  artifact exports. A different reviewer replayed the script in a separate store
  and checked the selected interpretations against the retained source bytes.
  The 21 observations are **operator-authored verification**, not model output or
  gold labels. The missing-key-only observation is not counted as a quoted,
  fully-attributed observation; its absence proof is checked separately.
- **61 frontend tests**, TypeScript and the production build passed. Browser
  inspection of the actual API-backed reports checked source contexts, distinct
  populations, citation expansion, long paths, exact source versions, scoped
  absence, reconciliation and null forecasts. No console errors were observed.
  Temporary read-only QA services were stopped; the main local app was refreshed
  without importing the verification cases into its account.
- The [Inspect adapter spike](decisions/inspect-adapter-spike.md) executed six
  synthetic attempts through the real runtime, retained one deliberate failure,
  and reused terminal receipts without additional provider requests. All nine
  retained evidence files matched their checksums. This qualifies a serial
  feasibility path only; delegated execution, transcript/budget parity, interrupted
  processes and real-provider operation remain required before adoption.

The next M1 gate is a narrowly scoped, independently checked reference/evaluation
contract. Matching source text and preserving its structure do not establish
semantic entailment, clinical correctness, completeness or predictive quality.
Real provider-driven comparison, authenticated market operation, options lifecycle
qualification and public repository publication remain open. Resume claims have
not been expanded to imply those outcomes.
