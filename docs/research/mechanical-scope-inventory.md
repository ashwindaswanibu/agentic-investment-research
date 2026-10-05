# Frozen-source inventory for a mechanical extraction gate

Status: proposed scope, inspected on 2026-10-05. This document is an engineering
inventory, not a reference package, answer key, implemented score, or independently
adjudicated clinical ground truth. It makes no efficacy or investment claim.

The six JSON blobs under
`artifacts/benchmark-development/clinical-development-v1/package/blobs/` were read
directly for this pass. Their canonical JSON SHA-256 digests were recomputed and
matched all six manifest content hashes. No verification example or candidate
dossier was consulted in this pass. The author previously contributed to the
verification example, so this source reinspection does **not** establish fully
independent reference authorship; a separate reviewer and explicit provenance are
still required before references are frozen.

The current package remains unlabelled and extraction-only. All `published_at`
and `available_at` manifest fields are null; acquisition was on 2026-10-05. These
are retained current snapshots, not evidence of historical availability. Do not
refresh a live URL in place of a pinned blob during evaluation.

## Exact source bindings

The table abbreviations below bind to these complete source identities. Hashes
are **evidence-artifact content hashes**, not the separate raw response digest
carried in provenance. Every locator must retain the full hash.

| Binding | Exact source ID | Content SHA-256 | Primary source |
| --- | --- | --- | --- |
| V | `ctg-NCT03525444-current-20261005` | `937f44a239b920a872ae02e7f855a333c927a50d8dff21bcfbdf42387db9a9c9` | [NCT03525444](https://clinicaltrials.gov/study/NCT03525444) |
| VP | `pubmed-31697873-efetch-20261005` | `2876f5bb9fa2130d78c7cea9aff920c24ead9c9b4b613b097f95731a889cb499` | [PMID31697873](https://pubmed.ncbi.nlm.nih.gov/31697873/) |
| C | `ctg-NCT05643742-current-20261005` | `475c4693be22469e0eb3eb7d559d6d7cd7d0913455a44f42ba7b78f186b68586` | [NCT05643742](https://clinicaltrials.gov/study/NCT05643742) |
| D | `ctg-NCT00045968-current-20261005` | `b253371514a0bfee28398af0d040f64f88176101e39a43e7c74a252b26e1cbdc` | [NCT00045968](https://clinicaltrials.gov/study/NCT00045968) |
| DP1 | `pubmed-29843811-efetch-20261005` | `66b32303221ab2eb791946269e69bc377d6a813ea7145453853e48d329544501` | [PMID29843811](https://pubmed.ncbi.nlm.nih.gov/29843811/) |
| DP2 | `pubmed-36394838-efetch-20261005` | `7c3e98b590e8d929f978f780c54200cc7bad40ab41ee0e22a247c5a6972919bf` | [PMID36394838](https://pubmed.ncbi.nlm.nih.gov/36394838/) |

## Recommended first scope

Use a small **guided, source-specific mechanical extraction diagnostic**:

- Three enrollment observations: count and reported actual/estimated status.
- Four protocol endpoint observations: exact measure text and timeframe, including
  the two separate CTX112 entries whose measure strings distinguish study phases.
- Three posted-outcome contexts in the Vertex record and their five denominator
  observations, preserving each owning outcome and its local group identity.
- Three registry results flags and two literal missing-key observations.

This is 20 proposed observations across the three families, with multiple explicitly
declared fields per observation. It is not a clinical completeness score. Freeze
the final included field set and denominator before running a candidate; do not
expand it opportunistically after inspecting outputs. Do not include every field
in an observation merely because the candidate schema requires that field to exist.

The public mapping may expose neutral observation/context IDs, source hashes,
exact pointers, local group IDs, permitted normalizations and eligible fields.
It must not carry expected values, expected `FieldValue` states, quotations chosen
to answer the question, or IDs such as `missing-results` that encode an answer.
This curated-location diagnostic intentionally removes source discovery from the
task; any reported agreement must say so. This engineering inventory should not
be silently injected as candidate instructions or a hidden reference.

## Enrollment and source-reported status

For each of V, C and D, the context pointer is
`/record/protocolSection/designModule/enrollmentInfo`. The source/hash binding
above applies separately to every row; no cross-source count substitution is
allowed.

| Sources | Exact field pointer | Observed raw JSON type | Allowed deterministic handling |
| --- | --- | --- | --- |
| V, C, D | `/record/protocolSection/designModule/enrollmentInfo/count` | integer | Exact nonnegative integer; `count_normalization=none`. Boolean, numeric string, null and omitted field are different. |
| V, C, D | `/record/protocolSection/designModule/enrollmentInfo/type` | string | Explicit field-specific dictionary `ACTUAL → actual`, `ESTIMATED → estimated` for `reported_status`; reject an unexpected token rather than guessing. |

These are registry enrollment observations. Do not rename them randomized, dosed,
analyzed or publication-reported populations. The field's reported actual/estimated
status can be preserved without deciding whether the registry is the most accurate
account of the study.

Each record also has a string at
`/record/protocolSection/statusModule/overallStatus`. This is a different kind of
status, not enrollment actual/estimated status. In particular, a source literal
`UNKNOWN` remains a present source value; it is not an absent field or an automatic
candidate abstention. Exclude overall study status from this initial dossier score
unless an explicit output field and normalization rule are added first.

## Protocol endpoint definitions and timeframes

Each listed context is the exact endpoint object. Both field values are raw JSON
strings. Keep array entries separate even when they share a source, trial or
primary role. Copy the source definition and timeframe verbatim; a future
whitespace-only rule must be declared and versioned before use. Do not remove
phase prefixes, translate clinical terms, convert duration to a calendar date, or
accept free-form synonyms through an LLM judge.

| Binding | Exact context pointer | Exact definition field pointer | Exact timeframe field pointer |
| --- | --- | --- | --- |
| V | `/record/protocolSection/outcomesModule/primaryOutcomes/0` | `/record/protocolSection/outcomesModule/primaryOutcomes/0/measure` | `/record/protocolSection/outcomesModule/primaryOutcomes/0/timeFrame` |
| C | `/record/protocolSection/outcomesModule/primaryOutcomes/0` | `/record/protocolSection/outcomesModule/primaryOutcomes/0/measure` | `/record/protocolSection/outcomesModule/primaryOutcomes/0/timeFrame` |
| C | `/record/protocolSection/outcomesModule/primaryOutcomes/1` | `/record/protocolSection/outcomesModule/primaryOutcomes/1/measure` | `/record/protocolSection/outcomesModule/primaryOutcomes/1/timeFrame` |
| D | `/record/protocolSection/outcomesModule/primaryOutcomes/0` | `/record/protocolSection/outcomesModule/primaryOutcomes/0/measure` | `/record/protocolSection/outcomesModule/primaryOutcomes/0/timeFrame` |

CTX112's two entries explicitly name different phases in their measure text. The
mechanical task preserves those strings and their pairings; it need not infer a
phase from intervention timing or classify a new endpoint ontology. Mapping the
`primaryOutcomes` container to source-reported role `primary` is a declared
structural rule, not evidence of original prespecification.

## Posted outcome denominators and local group identity

All rows in this section bind to V. The following complete pointers define three
distinct context containers:

| Context shorthand | Exact context pointer |
| --- | --- |
| O0 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0` |
| O9 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9` |
| O12 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/12` |

For each container, include an endpoint observation whose source definition is
the string at `context + /title` and timeframe is the string at
`context + /timeFrame`. These are exact pointer concatenations, not searches.
The optional source-reported role uses the string at `context + /type` with only
the declared `PRIMARY → primary` / `SECONDARY → secondary` dictionary. Preserve
the source string at `context + /populationDescription` as contextual evidence;
do not score a semantic rewrite or derived population-stage classification.

| Context | Exact denominator-value field pointer | Raw type | Exact local-ID field pointer | Group descriptor object pointer |
| --- | --- | --- | --- | --- |
| O0 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/denoms/0/counts/0/value` | string | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/denoms/0/counts/0/groupId` | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/groups/0` |
| O0 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/denoms/0/counts/1/value` | string | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/denoms/0/counts/1/groupId` | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/groups/1` |
| O9 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/denoms/0/counts/0/value` | string | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/denoms/0/counts/0/groupId` | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/groups/0` |
| O9 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/denoms/0/counts/1/value` | string | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/denoms/0/counts/1/groupId` | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/groups/1` |
| O12 | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/12/denoms/0/counts/0/value` | string | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/12/denoms/0/counts/0/groupId` | `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/12/groups/0` |

The descriptor's `/id` and `/title` are strings. Match the count's `groupId` to a
**unique** descriptor `/id` within that outcome's own `groups` array; the observed
positions above are not permission to join arbitrary arrays by index. The
denominator units are strings at:

- `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/0/denoms/0/units`
- `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/9/denoms/0/units`
- `/record/resultsSection/outcomeMeasuresModule/outcomeMeasures/12/denoms/0/units`

Candidate count normalization may be `integer_from_digit_string` only when the
retained source is a string matching the declared decimal-digit grammar. Keep
the raw string citation and normalize only this count field; never coerce group
IDs or units. State whether the accepted grammar is ASCII `[0-9]+` and enforce it
consistently; the inspected selected values meet that grammar. No trimming,
decimal rounding, commas, exponent parsing or sign handling is needed here.

A valid match must bind **value + full source hash + outcome container + local
group ID + denominator units + reciprocal endpoint link**. The same number in a
different group or outcome is not a correct answer. The repeated local ID in O0
and O12 resolves to different source group titles. Treating it as a global arm ID
would erase that distinction. Public structural mappings may identify each
container/local ID, but should not smuggle in inferred treatment equivalence.

The model's group locator has no separate group-title output field. Therefore the
retained `/title` is identity-verification evidence, not a new secretly scored
candidate field. If title extraction itself becomes a target, its output contract
must be introduced explicitly first.

## Registry availability and exact missing-key evidence

The context pointer is `/record` for each source in this section.

| Bindings | Exact field or proof target | Observed raw type/structure | Deterministic scope |
| --- | --- | --- | --- |
| V, C, D | `/record/hasResults` | boolean | Preserve an exact boolean and bind `available_source_ref` to this pointer. Never substitute zero, null, string text or a guessed absence state. |
| C, D | parent `/record`, exact key `resultsSection` | parent object; key absent in these retained snapshots | Validate parent integrity and object type, then exact key nonmembership. This is a `source_absent` proof of one JSON key, not a fabricated boolean scalar. |

V has an object at `/record/resultsSection`; do not invent a scalar `true` citation
to the object. Its existing `/record/hasResults` boolean is sufficient for the
initial availability observation. A missing parent, failed lookup, disallowed
artifact, corrupt hash or invalid JSON pointer is a failed verification, never
evidence of absence. Neither a registry flag nor missing resultsSection establishes
absence of publications or results outside this retained record.

Absence-proof observations have no quotation reference. Report their verified
missing-key checks separately from quotation-reference coverage; do not lower a
mechanical extraction score solely because an absent field has no invented quote.

## Publication blobs inspected, but semantic labels excluded

VP, DP1 and DP2 each retain PubMed XML in the JSON string at `/text`; that is the
exact JSON field and source context anchor. There are no nested JSON numeric
enrollment fields in those blobs. Their XML article/abstract sections were read
directly to identify scope boundaries:

| Binding | Exact JSON pointer / raw type | Relevant retained XML section labels | Excluded interpretation |
| --- | --- | --- | --- |
| VP | `/text` / string | `METHODS`, `RESULTS` | Separating randomized-and-dosed population from registry enrollment; classifying randomization or endpoint semantics from prose. |
| DP1 | `/text` / string | `METHODS`, `RESULTS` | Interpreting original allocation, crossover, analysis population and prose primary endpoint. |
| DP2 | `/text` / string | `DESIGN, SETTING, AND PARTICIPANTS`, `MAIN OUTCOMES AND MEASURES`, `RESULTS` | Distinguishing original randomized assignment from an external nonrandomized analysis within one source, and assigning population/endpoint roles. |

Parsing an XML section label or checking exact quotation presence is mechanical;
the clinical meaning assigned to that passage is a different target. A quoted
integer's existence is not proof that it represents the requested enrolled,
randomized, dosed or analyzed population. Avoid a regex-derived population
reference under the mechanical label. If publication extraction is later scored,
freeze a text-locator/excerpt policy and independent semantic reference process
before producing expected field values.

## Explicit exclusions and the next gate

Exclude from the first mechanical score:

- Prespecification, amendment chronology, original-vs-current endpoint precedence,
  historical availability and protocol/SAP completeness.
- Reconciliation entailment, clinical comparability, causal validity, treatment
  benefit, statistical significance, risk of bias and investment conclusions.
- Population-stage labels inferred from prose, sums across denominators, global
  arm equivalence, and any assumption that matching totals imply matching people.
- Semantic endpoint paraphrase, clinically equivalent units/timeframes, and
  readout dates inferred from study completion dates.
- Literature-wide absence and treating source `UNKNOWN`, explicit null, false,
  absent key, candidate omission and unresolved interpretation as interchangeable.

Before scoring: freeze public identity mapping and eligible fields; specify exact
normalizations and omission handling; prepare references directly from retained
source fields; obtain independent review of bindings and scope; record reference
method as programmatic/mechanical with named review provenance; then freeze the
package and tests. Candidate outputs must not be copied into references.

Report operational validity, exact source attribution and scoped extraction
agreement separately. Three development families do not establish general model
quality, clinical validity or performance on held-out issuers. See
[the evaluation protocol](../research-evaluation-protocol.md) and
[ADR 0003](../decisions/0003-clinical-reference-scope.md).
