# Registered forecasts and outcome review

Recorded 2026-10-05, America/New_York. Companion to
[ADR 0008](../decisions/0008-forecast-lifecycle.md). This closes a bounded workflow
gap between saved hypotheses and later outcomes. It does not qualify forecasting
skill, autonomous adjudication, options operation or investment performance.

## Implemented path

The **Forecasts** tab registers binary questions against exact hypothesis versions
and existing evidence. It retains the event window, Yes/No/unresolvable rules,
designated resolution source, probability or abstention, and stated baseline.
The `register_forecast` agent tool has the same implementation; only researcher
and coordinator roles may call it. Its schema and permissions appear in the
[generated architecture](../generated/agent-architecture.md).

The server records registration under the case write lock and checks the event
start again immediately before commit. Source retention/acquisition dates cannot
be in the future. Old dossier prose is never retroactively promoted. The timing
record does not prove absence of prior outcome knowledge or sound question design.

After the event window, a write-authorized operator can resolve against retained
evidence. Exact source hashes, excerpts and optional JSON pointers are checked;
semantic entailment, event timing and compliance with the prescribed source rule
remain the operator's responsibility. Agents cannot adjudicate outcomes. No
independent human review is implied by the `operator_api` origin label.

Corrections append against an explicit previous resolution. A case lock serializes
competing corrections. An identical retry returns its original artifact even when
a later correction exists. Every resolution remains inspectable. Sources labeled
synthetic keep that label through hypothesis lineage and correction history.

Each resolved non-abstained record shows `(p-y)^2`, the baseline loss, and baseline
loss minus forecast loss. An unresolvable outcome has no score; it is not No.
The view retains pending, due, abstained and unresolvable records. There is no
aggregate score, independence assumption, calibration claim or trading permission.

## Executed walkthrough

[forecast_lifecycle_verification.py](../../examples/forecast_lifecycle_verification.py)
uses the actual FastAPI routes and an actual short future event window. It waits
for that window to close rather than injecting a past registration timestamp.
Every report, probability and TEST event is explicitly invented.

```sh
.venv/bin/python examples/forecast_lifecycle_verification.py \
  --database-url sqlite:///./data/researchdesk.db
```

The command creates a new case on every run. It requires development dependencies
for the in-process HTTP test client. It makes no external network/model request,
launches no agent task, and does not mutate the paper ledger.

The saved local receipt is `artifacts/forecast-lifecycle-verification/api-walkthrough.json`.
Case `03f9f633-920f-4944-9101-5ce268ad80f1` initially contained five forecasts, one
in each of the pending/due/abstained/unresolvable/resolved states. Its primary
forecast `85ca67fd-0fbd-4346-84cd-5b45ac580bb2` declared p=0.7 and baseline=0.5:

| Outcome version | Forecast loss | Baseline loss | Improvement |
|---|---:|---:|---:|
| Preliminary Yes | 0.09 | 0.25 | +0.16 |
| Corrected No | 0.49 | 0.25 | −0.24 |

The original resolution and correction remain retained. Retrying the preliminary
request returned its exact original ID without displacing the correction. The
script also verified an unresolvable data gap and an explicit abstention remain
unscored. These numbers are arithmetic checks, not observations of forecasting skill.

## Browser verification and fixes

The local production build was inspected at desktop width and 390×844. The browser
registered a sixth synthetic forecast at 65% versus a 50% baseline; local date entry
was converted to explicit UTC. It rejected a deliberately absent quotation, accepted
the correct retained excerpt, opened the exact evidence/hash, and appended a later
unresolvable correction while keeping the superseded No judgment. The latter
illustrates an operator correcting an interpretation that exceeded the source;
it is not automated semantic review. The remaining original scored record still
shows the intended 0.49 versus 0.25 comparison.

Browser testing found a real integration defect: the Next.js proxy allowlist had
not admitted `/forecasts/{id}/resolutions`, so registration worked but resolution
returned 404. The route is now admitted, with a regression checking propagation
of correction conflicts, session cookies and idempotency keys. The full UI path
then succeeded. Citation errors were shortened into an actionable source-check
message. `?tab=forecasts` opens this view directly, with a case-screen regression.

At phone width the settled layout had a 390-pixel document width and no main-content
element wider than the viewport. The sidebar completes its existing slide-away
transition. Forms, exact evidence inspection and history remain available; this
does not certify the broader workbench's accessibility or all device/browser pairs.

## Software checks and limits

- The full Python suite passed **1,290 tests**, with 22 environment-dependent skips
  and the existing Starlette/httpx deprecation warning. After the final error-message
  edit, the focused lifecycle suite passed **55 tests**, with three PostgreSQL
  cases skipped because no disposable PostgreSQL test database was configured.
- Focused cases include expiry after flush/atomic rollback, lease loss, concurrent
  correction conflict, old retries after corrections, read-only/cancelled writes,
  invalid citations, future receipts, protected sources, abstentions, retained
  history beyond the ordinary 500-artifact library cap, and in-memory SQLite's
  shared-connection transaction behavior. The transaction guard was corrected to
  avoid opening a nested read session inside that SQLite write transaction.
- The full frontend suite passed **129 tests**. The production webpack build and
  TypeScript passed. Subsequent presentation cleanup kept the existing focused
  case/forecast interaction checks passing. Ruff, diff whitespace and the generated
  architecture drift check passed.

The shared preview opens directly at
`http://127.0.0.1:3000/cases/03f9f633-920f-4944-9101-5ce268ad80f1?tab=forecasts`.
The provider-setup banner is omitted on this operator workflow, which can function
without model credentials; the environment indicator and disabled research-launch
button still show provider readiness. The introductory copy was shortened so
forecast records appear sooner in the first screen.

Only SQLite was executed for this lifecycle here. PostgreSQL race cases remain a
separate integration gate. Operator source pickers use the existing bounded case
artifact listing; older sources outside that listing are not yet selectable through
these forms. The forecast-history endpoint itself returns the complete retained
case history and does not use that library cap.

No schema migration is required. For operational rollback, stop new writes with
the existing read-only setting while retaining a reader that recognizes the two
new artifact kinds; do not delete historical forecast/resolution artifacts or
substitute an old client that cannot decode them.

The substantive next dependency remains an authenticated research pilot with
predeclared baselines, independently reviewed outcomes and sufficient prospective
observations. This component records those decisions; it does not supply the model,
resolve economic uncertainty, validate a baseline or accelerate real event maturity.
