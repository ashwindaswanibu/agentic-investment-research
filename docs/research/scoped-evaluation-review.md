# Independent review: scoped v2 mechanical evaluation

Recorded: 2026-10-05. Design review only: no references, labels, scores, model runs
or application-code changes were produced. Reviewed [ADR 0003](../decisions/0003-clinical-reference-scope.md),
the [evaluation protocol](../research-evaluation-protocol.md),
[observation models](../../src/researchdesk/research/observation_models.py),
[benchmark declarations](../../src/researchdesk/research/benchmark_models.py), and
primary evaluator documentation/source below.

## Recommendation and what this gate measures

Implement a pure, versioned, field-scoped comparator before adapting it to an
evaluation framework. Call its result **guided registry extraction agreement**.
Public source locations deliberately remove much of source discovery and answer
alignment from the task. This is useful for finding wrong population bindings,
type coercion, omissions and version mistakes, but cannot establish clinical
entailment, successful reconciliation, research completeness or agent superiority.

The proposed initial scope—registry enrollment/status, selected endpoint text and
timeframes, results flags/key absence, and outcome-specific counts—is defensible.
Exclude publication-prose interpretation, prespecification and causal/comparator
judgments from this mechanical score. Keep their observations reviewable without
turning an unreviewed interpretation into a reference answer.

This advances M1's measurement prerequisite, not its research-quality promotion
gate. Include a deterministic source-projection comparator as a cheap engineering
baseline. An agent can otherwise earn a high score by copying supplied locations
while adding unsupported conclusions elsewhere. A later independent claim review
must assess those conclusions and whether material conflicting evidence was
recognized. Three already-discussed development families remain development data.

## Primary implementation comparisons

| Candidate | Relevant behavior and decision |
|---|---|
| Inspect | A custom scorer receives `TaskState` and `Target`, and can retain numeric/dictionary values plus diagnostic metadata. Use a thin adapter around our pure comparator; built-in text matching does not encode observation/source identity. [Custom scorer contract](https://inspect.aisi.org.uk/custom-scorers.html). |
| Inspect outcome handling | Incorrect/no-answer verdicts enter metrics; scoring errors, unscored values and omitted scores have different denominator behavior. Epoch reduction can hide an unscored repetition. Preserve our journal's complete attempt matrix and explicit counts instead of relying on displayed accuracy. [Scoring policy](https://inspect.aisi.org.uk/scoring-policy.html). |
| LangChain OpenEvals JSON match | A credible structured-extraction alternative: exact per-key checks, excluded keys, optional rubric grading and several list-matching modes. Current Python source also penalizes keys outside the reference and greedily aligns unordered items by matching values. It uses Python equality, which alone does not distinguish booleans from integers. Therefore it is not a drop-in comparator for our open-world, typed, public-ID contract. Preprojection and explicit type/identity checks would still be necessary; do not add its LLM judge to this mechanical scope. [Maintainer source](https://github.com/langchain-ai/openevals/blob/main/python/openevals/json/match.py). |

Inspect documentation was checked against the existing isolated **0.3.276** spike
installation's `scorer/_metric.py`, `_target.py` and `_metrics/accuracy.py`.
The source confirms that `Target` holds strings, `Score` can retain dictionary
values, and generic accuracy is not a substitute for field-specific aggregation.
No new adapter or evaluator was executed here. OpenEvals was inspected at its
current source URL; no version was installed or approved for adoption.

## Required invariants before implementation

1. **Freeze two distinct artifacts.** The public scope contains case ID, stable
   observation IDs, kinds, source/version hashes, owning context/group locations,
   scored field paths and public normalization rules. The private reference
   contains expected `FieldValue` states/values, accepted alternatives, evidence
   bindings, reviewer provenance and disagreements. Bind both hashes to the
   protocol. Do not reveal expected states through names such as “absent-results”
   or interpretation-bearing aliases. A public pointer is intentional task
   assistance, not hidden-reference leakage; describe that assistance accurately.

2. **References are independently prepared and reviewed.** Do not derive them
   from the operator verification dossier or candidate output. A second reviewer
   checks each mechanical rule against retained bytes independently of the
   projection implementation. This is engineering review, not a clinical-expert
   credential. Record prior exposure and any shared extraction code; do not call
   this a blinded holdout. Freeze before scored candidates; changes after errors
   require a new development version.

3. **Stable identity survives fresh stores.** Reference identity is manifest
   source ID plus exact content hash and pointer, not the original database UUID.
   Resolve it through each attempt's source-import receipt to the candidate's
   local artifact ID. Require consistent provenance, not an arbitrary artifact
   with matching bytes. Array positions are stable only within the pinned source
   version. A source upgrade is a new mapping/reference version.

4. **A correct value with the wrong binding fails.** A field match requires the
   expected observation kind, unique public ID, trial/context relationship,
   exact source/version and field-specific evidence location. An unrelated quote
   under a broad `/record` anchor is insufficient. Counts also retain the owning
   outcome/group, units and any declared endpoint relation. Matching the same
   integer from another population must not pass. One publication may support
   multiple distinct analysis contexts; source identity alone cannot merge them.

5. **Failures stay local; the denominator stays fixed.** Score only declared
   `(observation_id, field_path)` pairs, each exactly once. Omission or duplicate
   IDs fail the affected fields; ambiguous context IDs fail dependent fields.
   Never resolve duplicates by dictionary overwrite, best-value matching or
   choosing the most favorable occurrence. Extras cannot earn points or create
   false positives in this scope. Their schema/clinical problems remain separate
   dossier-review findings. Do not let an unrelated extra invalidate every scoped
   field through one global validation flag. An unreadable root/no selected final
   artifact is an explicit whole-attempt outcome.

6. **Compare typed states before values.** `present(null)`, `present(false)`,
   numeric zero, source absence, unresolved, not applicable and candidate omission
   are distinct. A missing-key proof needs the expected exact parent object/key;
   a missing or null parent does not prove absence. Source-reported unknown or
   not-applicable enums are not automatic epistemic uncertainty. Free-text
   justifications are retained, but their semantic quality is outside mechanical
   state matching. Correct uncertainty is creditable only under a declared rule,
   never because the private reference omitted that field.

7. **Normalizations are explicit and field-specific.** Require exact int/bool/null
   types; reject Python's `True == 1` equivalence. Integer-string count conversion
   may accept only the already supported canonical ASCII unsigned representation,
   while preserving its raw string citation and declared normalization. Enum
   mappings require a published lookup, not blanket case folding. Endpoint text
   can use an explicitly frozen whitespace rule, but not generic semantic
   similarity, punctuation deletion or unit/timeframe conversion. Never normalize
   pointers or meaningful key whitespace. `reported_in_text` establishes citation
   presence, not numeric entailment; exclude it from the initial mechanical scope.

8. **Check expressibility before approving a reference.** The current allocation
   type permits present `randomized`/`nonrandomized`, not the registry's literal
   `NA`. Exclude that field or explicitly review a field-specific mapping; do not
   hide an output-schema gap as candidate error. The same caution applies to
   source arrays mapped into free-text phase fields. Required but unscored dossier
   fields should have an honest unresolved representation; extraction-only
   `forecast: null` must remain valid.

9. **Private labels never enter execution.** Extend the existing public payload
   allowlist deliberately; never serialize a whole reference-bearing manifest or
   Inspect state into candidate prompts. Keep expected values, grader reports,
   reference paths and review notes outside candidate retrieval, task inputs,
   generated-code mounts and cross-case memory. Inspect targets/logs are visible
   to trusted adapter/operator code; they are not a security boundary themselves.
   Score after the immutable final selection, with no feedback loop during the
   attempt. Test leakage with sentinels through actual provider payloads/tools.

10. **Reference failure is not an incorrect candidate.** Preflight all source
    hashes, pointers, types, unique rules and nonempty scope before any run.
    Missing/corrupt reference data or scorer exceptions make the measurement
    incomplete. Block promotion and preserve the error; do not convert it to
    candidate zero, silently omit it or return a fabricated successful report.

## Safe accounting and minimum acceptance evidence

Persist one field receipt per declared pair: identity, candidate artifact hash,
source binding, rule version, outcome and reason. Suggested outcomes are match,
value/state mismatch, omitted, ambiguous identity, invalid scoped structure and
wrong source binding. Keep value agreement and provenance diagnostics separately
visible, but require both for a successful field. Do not split state/value/quote
checks into extra scoring opportunities that overweight one fact.

For each admitted case/arm/repetition, retain the frozen required-field count
`D > 0`, matched count `M`, final-selection identity and terminal execution status.
Report **delivered scoped coverage** as matched fields over all required fields
across admitted attempts, with failed/no-submission attempts delivering zero
matches. This is a system-delivery measure, not a claim that provider outages are
wrong clinical answers. Report conditional agreement among eligible submissions
only alongside its explicit attempt/field denominator and every excluded status.
Unlaunched planned attempts and reference/scorer failures remain separately visible;
an incomplete matrix cannot be promoted as a completed comparison. Do not label
open-world scoped agreement as general extraction precision/F1: unscored extra
assertions have not been adjudicated.

Show per-case and per-field-family results before pooled totals; many easy fields
must not conceal one wrong population assignment. Compare arms within case and
retain repetitions rather than treating every field as an independent study.
Inspect supports grouped/clustered metrics, but choosing a credible uncertainty
procedure still requires the frozen protocol; three purposive families cannot
support a general superiority claim. [Inspect metrics](https://inspect.aisi.org.uk/metrics.html).

Before a provider pilot, use explicitly synthetic mutations to prove: changed
source versions fail; repeated local group IDs cannot cross containers; a correct
value from the wrong pointer fails; duplicate/missing IDs affect only dependent
fields; additional legitimate observations leave the denominator unchanged;
null/false/zero/absence cannot interchange; missing parents fail absence proof;
disallowed count/text normalizations fail; attempt-local artifact IDs rebind
correctly; tampered references stop measurement; failed attempts remain counted;
and serialized candidate inputs contain no private sentinels. These qualify the
instrument. Independently reviewed references and later research-claim assessment
remain separate acceptance gates.
