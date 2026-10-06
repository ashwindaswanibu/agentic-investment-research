# ADR 0008: Connect registered forecasts to retained outcomes

Date: 2026-10-05. Status: implemented and locally verified; no forecasting skill established.

See [execution and browser evidence](../research/forecast-lifecycle.md).

## Job and stopping condition

A research conclusion must eventually face an outcome. Existing clinical dossiers
can carry forecast prose and supplied dates, but have no server registration time,
fixed baseline, resolution record or correction history. This leaves the reader
unable to tell what was predicted beforehand or whether confidence was warranted.

Complete one case-local path: hypothesis → immutable binary forecast → retained
outcome evidence → operator resolution → per-record comparison with the declared
baseline. Registration, inspection and correction must work in the browser.
Pending, abstained and unresolvable records remain visible. This is a component of
roadmap M3 while M1's authenticated research run remains pending. It does not
replace that leading research-quality gate or the pending options-engine comparison.

Stop after this workflow and its persistence, permissions, timing, provenance,
conflict, correction and browser checks pass. Do not build a tournament, leaderboard,
calibration dashboard, autonomous adjudicator, new scheduler or trade admission.

## Alternatives and research

1. **Extend only the freeform dossier.** Lowest immediate cost, but the existing
   document mixes claims, author-supplied dates and optional predictions. It cannot
   establish a locked prediction/resolution boundary. Keep those documents intact;
   do not silently promote them to registered forecasts.
2. **Reuse existing artifacts and transactional case locks.** Adds a narrow
   lifecycle with familiar provenance, role permissions, source inspection and
   retry recovery. This is the chosen integration: one immutable forecast plus
   append-only resolution versions, with no separately writable score database.
3. **Adopt an external forecasting platform.** Metaculus is a credible reference
   for explicit questions, dates, resolution authority and proper scoring. Its
   [question guidance](https://www.metaculus.com/question-writing/) requires clear
   terms, sources and fallback cases; its [FAQ](https://www.metaculus.com/faq/)
   distinguishes ambiguous/annulled questions from scored outcomes. Its
   [scoring implementation](https://github.com/Metaculus/metaculus/blob/main/scoring/score_math.py)
   supports a broader community/time-aggregation system than this local workflow.
   Adopting that stack would add an identity, data and operations boundary without
   resolving our immediate case-to-evidence gap. No code or service is imported.

The proper-scoring basis is [Gneiting and Raftery, 2007](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf).
For a binary outcome y in {0,1}, use the unscaled Brier loss `(p - y)^2`, lower
being better. Baseline improvement is `baseline_loss - forecast_loss`. Other
normalizations of the categorical quadratic score exist; expose this convention.
Proper scoring supports honest probabilities in expectation. A favorable result
on one selected event establishes neither calibration nor economic usefulness.
Sources inspected 2026-10-05; the platform source is a design reference, not a
pinned dependency or a claim that its scoring behavior is reproduced here.

## Contract and authority

- Bind the exact hypothesis hash and retained sources to the forecast. Keep its
  binary question, Yes/No/unresolvable rules, permitted resolution source,
  event window, probability, baseline probability and baseline rationale together.
  An abstention supplies a reason and no probability.
- The server stamps registration inside the write transaction. Require registration
  before the event window begins, and an end after its beginning. These dates name
  the **event window**, not the dates when a forecasting form opens. Do not accept
  user-supplied registration dates, retrospectively import old predictions or edit
  rules after submission. A changed belief can be a separate immutable record.
- Registration proves the application's chronology, not that the event was unknown,
  the model lacked prior information, the wording was sound or the baseline was
  credible. That requires substantive review. Repeated or correlated records are
  not independent events; this milestone has no aggregate score.
- Researchers/coordinators may register through the recorded tool registry.
  Operators may register in the workbench. Agents cannot resolve their forecasts.
  A write-authorized operator may resolve after the stated window ends, citing
  exact retained artifacts and explaining the application of the fixed rule.
  Resolver origin is an application authority label, not a verified person's name.
- Missing, conflicting or unusable evidence can produce **unresolvable**. Missing
  data does not automatically mean No. Neither unresolvable forecasts nor
  abstentions receive a forecast score.
- A correction must identify the current resolution. The transaction rejects a
  stale predecessor; retrying an already committed request recovers that exact
  result even after a later correction. Preserve every resolution and evidence
  version, expose the active one, and derive the current score from it.
- Verify cited hashes and excerpts/source pointers against retained content;
  reject protected labels, unrelated case references where disallowed, future
  retention/acquisition times and malformed citations. Citation validity is not
  semantic adjudication of a claim. The operator remains responsible for matching
  the prescribed source, event timing and rule to the evidence.
- Synthetic inputs remain visibly synthetic throughout. No record authorizes an
  order, changes a paper balance or contributes a claimed investment result.

## Acceptance cases frozen before implementation

| Case | Required result |
|---|---|
| p=0.7, baseline=0.5, Yes | Forecast loss 0.09, baseline 0.25, improvement +0.16 |
| Same forecast, corrected to No | Current loss 0.49, baseline 0.25, improvement −0.24; original Yes retained |
| Unresolved or unresolvable | No score; distinguish waiting/due from unresolvable |
| Abstention | Retain reason and outcome history; no forecast score |
| Registration reaches its event start before commit | Reject; no partially saved registration |
| Resolution before window end | Reject; no outcome artifact |
| Changed hash, wrong excerpt, future receipt or protected input | Reject; no false provenance receipt |
| Two corrections against one predecessor | Only one succeeds; loser receives a conflict |
| Retry after a later correction | Recover original request result, never reapply it |
| Cancelled/read-only case or agent resolution attempt | No unauthorized write |
| Browser | Register, inspect, resolve and correct; narrow layout, errors, read-only and source navigation remain usable |

The engineering demonstration uses explicitly invented event evidence and
probabilities. It may verify the real workflow with a short future event window;
it must not backdate the production path or pretend a model made a forecast.
Actual research runs, independent outcome adjudication, prospective observation
periods, calibration and selection-bias analysis remain separate evidence needs.
