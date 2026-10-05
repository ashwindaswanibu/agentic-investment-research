# ADR 0003: Define source-qualified clinical references before scoring

- Status: source-qualified v2 **candidate outputs are implemented**; the scoped
  reference contract and scoring changes below are **not implemented**.
- Recorded: 2026-10-05. Primary source snapshots acquired and read on 2026-10-05.
- Scope: the three-family [clinical development corpus](../research-benchmark-data.md)
  and the next M1 evaluation gate.
- Current evidence: code inspection, retained public sources and synthetic validator
  tests. No independently adjudicated reference or real-corpus quality score exists.

## Decision and current boundary

Keep the development cases unlabelled. Separate **registry mechanical agreement**,
**cross-source evidence reconciliation**, and **operational provenance checks**.
Do not promote the ten-field registry projections into references declaring
`complete_for_schema`, and do not interpret a valid dossier as clinically correct.
An unscored provider pilot can establish execution and output-format behavior; it
cannot establish extraction accuracy, research superiority, efficacy or trading value.

The immediate proposed scoring scope is agreement with explicitly selected fields
in an exact registry snapshot. Reconciliation of registrations, publications,
populations and analyses requires a source-qualified contract and independent review.
The current extraction scorer does not implement that contract. The
[implemented v2 output design](../research/clinical-observation-design.md)
preserves these distinctions through source contexts, observations, scoped
missingness and explicit reconciliation; it remains separate from reference
adjudication and scoring. The legacy scorer rejects v2 rather than flattening it.

Scalar attribution is already implemented, separately from this proposal:
[`SourceReference`](../../src/researchdesk/research/models.py#L19),
[`_scalar_excerpt`](../../src/researchdesk/research/quality.py#L123) and
[`validate_dossier` source checks](../../src/researchdesk/research/quality.py#L329)
accept exact JSON-pointer citations of finite numbers, booleans and null. The
excerpt must equal the full canonical JSON scalar spelling used by artifact
hashing: for example `405`, `false` or `null`. This is a parsed-value convention,
not preservation of the original JSON numeric lexeme; `1` and `1.0` differ.
Missing paths, objects, arrays and nonfinite numbers fail. Text quotations retain
case-sensitive, whitespace-normalized substring matching within one source string.
Both paths require exact artifact identity and full-content hashes. These checks
prove retained data presence, not clinical truth or claim entailment.

## Why these real cases require a narrower interpretation

| Family | Retained source statements | Required distinction |
|---|---|---|
| Vertex VX17-445-102 | [NCT03525444](https://clinicaltrials.gov/study/NCT03525444) reports enrollment 405, `ACTUAL`; [PMID31697873](https://pubmed.ncbi.nlm.nih.gov/31697873/) describes 403 participants randomized and dosed. | Retain each denominator with its source and population definition. Neither is automatically the current schema's per-arm `planned_n`, and the discrepancy alone does not establish which source is wrong. |
| CRISPR CTX112 | [NCT05643742](https://clinicaltrials.gov/study/NCT05643742) lists one experimental arm, allocation `NA`, intervention model `SEQUENTIAL`, phase 1/2, estimated enrollment 120 and `hasResults=false`. | One arm does not license rewriting the structured design as `SINGLE_GROUP`. No posted registry results does not mean no results elsewhere. Phase-specific endpoints must remain separate. |
| Northwest DCVax-L | [PMID29843811](https://pubmed.ncbi.nlm.nih.gov/29843811/) describes primary progression-free survival and secondary overall survival; [PMID36394838](https://pubmed.ncbi.nlm.nih.gov/36394838/) describes a later externally controlled nonrandomized overall-survival analysis. [NCT00045968](https://clinicaltrials.gov/study/NCT00045968) combines randomized/parallel design fields with a primary overall-survival endpoint referring to external controls. | Original allocation and later reported analysis are distinct. One unqualified allocation or endpoint label cannot represent both. Current registration plus abstracts does not establish amendment timing, prespecification or external-control validity. |

These are observations about the frozen acquired records, not assertions that the
live pages cannot change. Exact bytes, acquisition times and hashes are retained
in the corpus manifest. Historical registry versions and complete protocol/SAP
documents were not acquired. Present-day source content and publication dates do
not establish what was available at an earlier investment decision cutoff.

## Current schema and scorer limitations

1. [`TrialDesign`](../../src/researchdesk/research/models.py#L42) and
   [`ClinicalTrial`](../../src/researchdesk/research/models.py#L67) allow one design
   per trial ID, without an analysis or source-version axis.
   [`TrialArm`](../../src/researchdesk/research/models.py#L49) has `planned_n`, not
   typed total, randomized, dosed or analyzed population counts. The extraction
   schema also lacks typed registry-results availability and intervention model.
2. [`ClinicalExtraction`](../../src/researchdesk/research/models.py#L174) excludes
   claims, reasoning and forecasts. [`_extraction`](../../src/researchdesk/research/quality.py#L444)
   removes claim links from dossier projections. Thus the extraction score does
   not measure whether conflicts were recognized, an inference is supported or
   abstention was justified.
3. [`ExtractionReference`](../../src/researchdesk/research/models.py#L187) requires
   `coverage="complete_for_schema"` but does not establish that coverage.
   [`score_extraction`](../../src/researchdesk/research/quality.py#L516) treats extra
   candidate fields as false positives and omitted reference values as unsupported
   candidate assertions. A partial reference can penalize correct additional facts.
4. [`_flatten`](../../src/researchdesk/research/quality.py#L469) aligns records using
   supplied trial/arm/endpoint IDs and normalizes only Unicode, case and whitespace.
   Different reasonable IDs can create cascading errors. Equivalent endpoint
   wording such as “4 weeks” and “From Baseline at Week 4” can mismatch. All
   mismatches except arm labels currently become critical errors; that is not a
   clinically adjudicated severity rule.

File anchors describe the implementation inspected on the recorded date; named
classes/functions are authoritative if later edits move line numbers.

## Proposed minimum source-qualified contract

The following are requirements for a future version, not existing API fields.
Keep source-reported observations distinct from conclusions about them.

| Element | Minimum information |
|---|---|
| Case scope | Declared question, exact included source hashes, snapshot/cutoff policy, eligible fields, excluded judgments and evaluation mode. |
| Observation identity | Trial family and trial ID, source/version identity, analysis ID where applicable, stable public observation ID, and source pointer or exact passage. |
| Source binding | Artifact ID and full-content hash; registry/publication identifier; acquisition time; publication/availability evidence with unknown values explicit. |
| Enrollment observation | Count, unit, trial/arm scope, population definition, source-reported stage such as registered/randomized/dosed/analyzed, and actual/estimated status. Do not derive unsupported denominator relationships. |
| Endpoint observation | Public endpoint ID, analysis/version, definition, timeframe, source-reported role, relevant population/comparison and units where available. |
| Prespecification | `yes`, `no` or unresolved, with evidence and rationale about the relevant version/timing. A current primary-endpoint label alone is insufficient. |
| Reconciliation | Linked source observations, compatible-context explanation or unresolved conflict, material missing evidence, and retained rationale. This must not silently overwrite either source. |
| Reference field | Explicit scored path, supported expected value or accepted alternatives, evidence binding, normalization rule, missingness rule and severity rationale. |

### Public identity and alignment

Freeze a candidate-visible mapping of trial, analysis, arm and endpoint identities
before collecting outputs. IDs should refer to source locations within frozen
versions, not depend on answer wording or a secret reference author's labels.
Publish identity/location information without expected answers or adjudication
rationales. For example, an endpoint ID may map to a particular primary-outcome
array entry under a named source hash. An index is only stable within that frozen
version; cross-version equivalence needs an explicit separately reviewed mapping.

Do not duplicate an NCT ID as though two analyses were independent trials. Preserve
family grouping in data splits and statistics. If an alternative scorer aligns
candidate-created IDs, freeze and test its matching rules before the run; do not
repair mappings selectively after seeing which architecture benefits.

### Unknown, absent and not applicable

Keep these states separate:

- **Present:** a source supplies a value, including a literal JSON null if present.
- **Source absent:** the specified field or information is not in the scoped source.
- **Unresolved:** the available evidence cannot support a value or reconcile a conflict.
- **Not applicable:** the concept does not apply, with an explicit basis.
- **Candidate omission:** the candidate did not provide a required scoped answer.
- **Outside scope:** the field is not assessed by this reference.

The proposed scoring policy must declare how each state is represented and judged.
A literal null is not automatically an assertion of clinical absence. Correct
uncertainty must not become a false positive merely because the reference omitted
the field. Conversely, unrestricted “unknown” must not receive credit for an
explicitly reported required value. Optional out-of-scope fields should not silently
enter a closed-world denominator; separately reviewed unsupported claims remain
relevant to dossier quality.

## Independence and acceptance gates

1. Freeze the source package, question, public identity mapping and scored scope.
   Keep selection rationales, projection files, references and review notes outside
   the candidate-visible package. The final manifest questions are the prompts;
   this public design document is not a candidate evidence source.
2. Prepare the reference ledger before inspecting candidate answers. A separate
   reviewer checks every scored field against retained evidence and records
   disagreements, resolutions and reviewer identity/version. Candidate agents or
   agreement between models cannot serve as independent adjudication.
3. Mechanical projections may bootstrap source extraction but must be checked
   independently of their extraction code. Label a result **mechanical registry
   agreement** when that is all the reference supports. Causal, prespecification
   and comparability judgments require suitable domain review; otherwise exclude
   them from scores and preserve unresolved questions.
4. Test the proposed contract and scorer on population differences, source versions,
   conflicting endpoints, legitimate synonyms, unknown/absent values and public-ID
   alignment. Declare severity rules rather than calling every textual difference
   clinically critical. Retain diagnostic failures separately from model scores.
5. Freeze schema, reference, scorer, runtime, model and protocol versions before a
   scored run. Keep operational checks, scoped extraction agreement and independently
   reviewed reconciliation as separate measures. Changes motivated by pilot errors
   create a new development version; do not silently rescore a frozen comparison.
6. Exclude these issuer/trial families from a later final holdout. Three purposively
   selected families support development, not population-level superiority claims.
   Follow the [evaluation protocol](../research-evaluation-protocol.md) for repeated
   trials, family-level comparisons, uncertainty and final promotion criteria.

M1 remains incomplete until the chosen scope is expressible, references satisfy
these gates and real runs retain auditable outputs. Scalar citation support closes
one input-contract defect; it does not complete the reference or evaluation work.
