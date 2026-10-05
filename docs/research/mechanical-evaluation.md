# Guided extraction: a bounded measurement prerequisite

Updated 2026-10-05. Engineering verification only; independent reference review
and actual model comparisons remain pending.

## Why this belongs in the product

The product goal is an accountable agentic research and paper-trading workflow:
detect a research need, create a useful specialist, build and verify tools,
investigate competing explanations, then support a monitored portfolio decision.
This component answers one narrower prerequisite: can an output preserve a
requested source fact and its correct population/outcome binding? It does not
answer whether the research is insightful, clinically sound, or profitable.

The source-qualified dossier exposed ambiguities in an earlier trial-wide answer
format. An exact source-scoped check is justified for those ambiguities. A generic
grader platform, more scheduling machinery or a large benchmark dashboard is not
part of this change. The alternatives and primary-source comparison are in the
[scorer review](scoped-evaluation-review.md); the selected fields and exclusions
are in the [source inventory](mechanical-scope-inventory.md).

## Contract and decisions

- The public scope freezes case/trial/context/observation identities, exact source
  versions and requested field pointers, permitted normalizations, and required
  group/endpoint relationships. It contains no expected values or states.
- A separate private reference derives only those fields from retained bytes.
  Source absence requires an existing parent object and exact missing key.
  Wrong references stop measurement; they are not candidate failures.
- The comparator keeps one denominator entry per declared field. Wrong values,
  omissions, duplicate identities, wrong population bindings and absent citations
  have explicit outcomes. Unrelated extra observations cannot earn points or
  erase correct scoped fields. Whole-dossier schema validity is separate.
- A deterministic baseline receives only the public scope and source artifacts.
  It copies supported scalars and preserves typed missingness. It creates no
  clinical claims, reconciliation conclusions, forecasts or trades. This is an
  intentionally cheap comparator for a task that supplies source locations.
- Operator comparisons retain immutable input/source/reference digests using
  protected artifacts. Agent tools cannot read the keys or reports. Optional
  public scopes are bound into frozen protocols; legacy protocol hashes remain
  unchanged when scopes are absent.

Reference records are automated source projections, not expert-adjudicated gold.
The author had prior source familiarity. The review-agent interruption left
independent package/integration review unfinished; reviewers remain empty. No
benchmark protocol or candidate optimization was performed on these references.

## Acceptance evidence and reproducibility

The local package `artifacts/mechanical-reference-package-20261005T155201Z-859ae4/`
contains six original evidence blobs, three public scopes, three private keys and
three projection ledgers. Its index digest is
`1dd46f162b8cca89e3e7b497177f721a96156dd987d3911cc8a81f35e0bb6df6`.
It retains 20 requested observations and 38 fields across three development
families. The original unlabelled acquisition package is unchanged. These local
source and private-key files are ignored by Git; the reproducible builder is
[build_mechanical_reference_package.py](../../examples/build_mechanical_reference_package.py).

The real-source workflow verification produced:

| Retained record | Declared fields | Deterministic baseline matches | Deliberate error probe matches |
| --- | ---: | ---: | ---: |
| NCT03525444 | 24 | 24 | 23 |
| NCT05643742 | 8 | 8 | 7 |
| NCT00045968 | 6 | 6 | 5 |

Each probe deliberately increments one count. These are instrument checks, not
agent outcomes, a research-quality score or evidence of superiority. All three
baseline dossiers passed source-attribution validation. Zero model calls were
made. Results and an isolated application database are retained in
`artifacts/mechanical-evaluation-verification-20261005-v1/`; the main database was
not used.

The full local Python suite passed **991 tests**, with 19 environment-dependent
skips and an existing Starlette/httpx deprecation warning. The frontend passed
**69 tests**, TypeScript and its production build. The actual paired report was
opened through a temporary read-only API/workbench: 23/24 versus 24/24 rendered
correctly, the intended wrong count was visible, and the browser console had no
errors. This is layout/interaction verification of this report, not approval of
the broader workbench design.

```sh
.venv/bin/python examples/build_mechanical_reference_package.py --help
.venv/bin/python examples/mechanical_evaluation_verification.py \
  --package artifacts/mechanical-reference-package-20261005T155201Z-859ae4 \
  --output artifacts/mechanical-evaluation-verification-NEW-VERSION
.venv/bin/python -m pytest tests/test_scoped_models.py tests/test_scoped_quality.py \
  tests/test_mechanical_projection.py tests/test_mechanical_workflow.py \
  tests/test_mechanical_bundle.py tests/test_mechanical_reference_package.py -q
```

Use a new output directory on every verification. The optional retained-source
tests require the original acquisition package; a fresh checkout reports an
explicit skip without it. Fixture-only software tests do not need that package.
The operator CLI `researchdesk evaluate-mechanical` accepts distinct frozen
candidate/baseline IDs, scope/reference JSON and a source-ID-to-local-artifact-ID
mapping. It is not an agent tool. The workbench renders field outcomes and source
bindings without exposing the expected answers.

## Stopping point and next useful work

This checkpoint ends at a working baseline, a verified paired comparison and a
readable report. Do not add more scoring abstractions without a demonstrated
failure in an actual workflow. Before using these references for a candidate
comparison, finish independent source/key review and freeze the effective
protocol, model, budgets and implementation. Changed references require a new
development version.

Return next to one authenticated end-to-end research run: evidence triggers a
capability gap, specialists collaborate on a useful tool, the tool is challenged,
and the final dossier is inspected against competing evidence. Guided extraction
is one diagnostic within that run. Broader claim/reconciliation review and a
budget-matched generalist comparison are still necessary. The current stage does
not promote autonomous trading, options admission or a resume performance claim.
