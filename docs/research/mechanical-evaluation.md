# Guided extraction: a bounded measurement prerequisite

Updated 2026-10-05. Engineering verification only. A separate independent automated
source review is now recorded below; actual model comparisons remain pending.

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
The author had prior source familiarity. The original package's authoring records
remain unchanged, including empty reviewer lists. A later review is retained as a
separate receipt bound to exact package and source versions. No benchmark protocol
or candidate optimization was performed on these references.

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
failure in an actual workflow. The source/key review described below addresses
the bounded factual reference gate. Before a candidate comparison, freeze the
effective protocol, model, budgets and implementation. Changed references require
a new development version.

Return next to one authenticated end-to-end research run: evidence triggers a
capability gap, specialists collaborate on a useful tool, the tool is challenged,
and the final dossier is inspected against competing evidence. Guided extraction
is one diagnostic within that run. Broader claim/reconciliation review and a
budget-matched generalist comparison are still necessary. The current stage does
not promote autonomous trading, options admission or a resume performance claim.

## Independent review and explicit normalization, v2

A separate reviewer checked all 38 expected fields, 13 source contexts and five
outcome-local group/endpoint bindings against the retained source objects, without
using candidate dossiers or importing the projection/comparator. It found no wrong
labels or bindings. Reading surrounding registry records and publication abstracts
also confirmed why source-specific enrollment, analysis populations and endpoint
contexts must stay separate. This is automated engineering review with prior source
exposure, not a blinded evaluation or a human clinical judgment.

The review exposed two implementation/contract discrepancies. V2 now serializes
complete field-specific `enum_map` entries for `enum_lookup`, and rejects source
tokens not in that exact mapping. The deterministic baseline and reference scorer
both enforce the declared 20-digit canonical-count limit. Generic `lowercase_enum`
remains readable for legacy packages but is not authored or admitted by the v2
auditor. Absent new fields are omitted from serialization: the three original
scope and reference hashes were reloaded and verified unchanged.

The new package is `artifacts/mechanical-reference-package-v2-20261005/`, digest
`dd8b7ff8e22ede3e3e5315ae264d30839600d82e5ae4f3de5ad716824ab22a74`.
Its recorded values and context identities remain unchanged; six enum fields have
explicit conversion contracts. The separate
[stdlib auditor](../../examples/audit_mechanical_reference_package.py) checks the
retained package without importing application extraction code. It produces a
new digest-bound receipt, never changes the package, and refuses to overwrite a
receipt. The executable checks source agreement; it does not adjudicate publication
prose or certify public authenticity or historical availability.

The successful receipt is
`artifacts/mechanical-reference-package-v2-audit-20261005.json`, SHA-256
`160c4ac90d50b1428631f2c81be33ff0a82b0e1c3585718fa79e75a9b5c422a6`.
It binds all 38 fields, 13 contexts, five group/endpoint bindings, six sources and
15 blobs. The 15 auditor tests include self-consistent wrong mappings, changed
counts, wrong groups, invalid absence proofs and refusal to overwrite a receipt.

```sh
.venv/bin/python examples/build_mechanical_reference_package.py --output-dir artifacts/NEW-PACKAGE
.venv/bin/python examples/audit_mechanical_reference_package.py \
  --package artifacts/NEW-PACKAGE --output artifacts/NEW-AUDIT.json
.venv/bin/python examples/mechanical_evaluation_verification.py \
  --package artifacts/NEW-PACKAGE --output artifacts/NEW-VERIFICATION
```

The v2 workflow verification again reproduced 24/24, 8/8 and 6/6 deterministic
matches and isolated each deliberate one-field count error. Its output at
`artifacts/mechanical-evaluation-verification-v2-20261005/` predates the separate
audit receipt, so its saved review status correctly remains pending at that run.
No model calls were made. This closes factual package checking only; genuine agent
use, substantive claim review and a budget-matched generalist comparison remain.

After these changes the full Python suite passed **1,235 tests**, with 19
environment-dependent skips and the existing Starlette/httpx deprecation warning.
Ruff and the diff whitespace check passed. There were no frontend changes in this
checkpoint; the earlier browser checks were not repeated.
