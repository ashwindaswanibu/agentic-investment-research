# Source-qualified clinical observations: standards review and v2 proposal

Recorded and primary sources read: **2026-10-05**. Status: primary-source design review with an implemented v2 output contract;
no independently adjudicated reference or clinical score. This document develops
[ADR 0003](../decisions/0003-clinical-reference-scope.md) using official data
definitions and the six retained sources in the
[development corpus](../research-benchmark-data.md). It concerns factual extraction;
it makes no clinical efficacy, predictive accuracy or investment claim.

## Recommendation

Build a compact dossier of **source-qualified observations and explicitly linked
reconciliation issues**. Preserve source-specific design, group identity, population
counts, endpoints and result availability. Reuse the existing source manifest and
citations. Do not reduce a study to one allocation label, one enrollment number or
one global set of arms, and do not adopt a complete clinical ontology for this stage.

This is our design inference from the sources below, not a claim that any standard
requires this exact JSON structure. ClinicalTrials.gov supplies the source semantics;
CONSORT supplies reporting distinctions; FHIR offers useful conceptual precedents.
None of these independently adjudicates the acquired trial records.

## Primary standards and practical distinctions

### ClinicalTrials.gov: protocol fields and results fields have different scopes

The official protocol definition treats enrollment as an estimated target or actual
total. It does not equate enrollment with treatment receipt or analysis membership.
Its outcome definitions separate title, description and timeframe.
[Protocol definitions](https://clinicaltrials.gov/policy/protocol-definitions#IntEnrollment).

The results definitions distinguish period entry/completion, population descriptions,
outcome-specific analyzed participants and other analysis units. The first period's
`STARTED` count concerns assignment; later periods retain their own boundaries.
Pre-assignment details can explain differences from enrollment. An analyzed count
belongs to the particular outcome and arm/group, not automatically the entire trial.
Preserve units such as participants versus eyes or lesions.
[Participant flow](https://clinicaltrials.gov/policy/results-definitions#Started),
[analyzed counts](https://clinicaltrials.gov/policy/results-definitions#SubjectsAnalyzed),
[analysis population](https://clinicaltrials.gov/policy/results-definitions#AnalysisPopulation).

The API metadata identifies enrollment count as an integer, but several result-count
fields as text. It defines `hasResults` as posted results on the public site.
Submitted, posted and retrieved dates have distinct meanings.
[Official API metadata](https://clinicaltrials.gov/api/v2/studies/metadata).

Exact API locations useful to our adapter, relative to the retained wrapper's
`/record` (array notation below describes a pattern, not an RFC 6901 pointer):

| Concept | Location | Required local interpretation |
|---|---|---|
| Registry enrollment | `/protocolSection/designModule/enrollmentInfo/{count,type}` | Keep count and `ACTUAL`/`ESTIMATED` together; do not populate per-arm planned counts. |
| Registered design | `/protocolSection/designModule/designInfo` | Keep allocation, intervention model and masking separately, with the source snapshot. |
| Registered endpoint | `/protocolSection/outcomesModule/{primaryOutcomes,secondaryOutcomes}[]` | Identify the specific collection entry; retain its timeframe and description. |
| Flow denominator | `/resultsSection/participantFlowModule/periods[]/milestones[]/achievements[]/{groupId,numSubjects}` | Include period, milestone, group and any milestone comment. |
| Baseline denominator | `/resultsSection/baselineCharacteristicsModule/denoms[]/counts[]` | Bind units and baseline population description; do not assume outcome membership. |
| Outcome denominator | `/resultsSection/outcomeMeasuresModule/outcomeMeasures[]/denoms[]/counts[]` | Bind the exact outcome, its `groups`, `populationDescription`, timeframe and units. |
| Reported analysis | `/resultsSection/outcomeMeasuresModule/outcomeMeasures[]/analyses[]` | Bind the selected comparison groups to that outcome container. |
| Posted result availability | `/hasResults`; presence of `/resultsSection` | State the registry scope; neither establishes whether results exist elsewhere. |

These paths were checked against the current official metadata and acquired JSON.
**Implementation inference:** preserve the raw JSON type as well as any normalized
count. Parse only an explicitly supported integer representation. Do not turn
unrecognized text or a missing value into zero, and do not treat `"203"` as a
JSON numeric scalar in a quotation merely because a downstream count is an integer.

### CONSORT 2025: population flow and analyses are separate reporting concepts

The official expanded checklist distinguishes:

- Item 22a: allocation, intervention receipt and primary-outcome analysis counts.
- Items 21b and 26: analysis membership/grouping, analyzed counts and available-data
  counts at the outcome timepoint.
- Items 9 and 10: trial design versus subsequent changes, including timing/reasons
  and outcomes or analyses that were not prespecified.
- Item 14: outcome variable, analysis metric, aggregation and timepoint.

These distinctions support preserving population membership and analysis context.
They do not authorize reconstructing an unreported flow count or prespecification
chronology. CONSORT is a randomized-trial reporting guideline; our CTX112 extraction
does not become a randomized-trial compliance assessment.
[Official CONSORT 2025 expanded checklist, items 9–10, 14, 21–22 and 26](https://www.consort-spirit.org/_files/ugd/b5740e_a6856e5e2cf94a1db5a8005853404160.pdf).

### FHIR R5: borrow distinctions, defer interchange implementation

FHIR `Evidence` distinguishes intended from observed variables and separately
represents study design, participant sample size and known-data count. These are
useful precedents for keeping the intended population apart from the measured one.
The R5 resource is trial-use, maturity level 1; adopting its entire resource graph
would add complexity without solving our reference-adjudication problem.
[FHIR R5 Evidence definitions](https://hl7.org/fhir/R5/evidence-definitions.html).

FHIR's missing-data vocabulary distinguishes unknown, not applicable, unsupported
and other reasons. Its JSON representation also uses null placeholders in repeated
primitive arrays. Therefore a raw JSON null cannot carry a universal clinical
meaning. Our proposed missingness states below are local evaluation semantics,
not a claim of FHIR conformance.
[R5 data-absent-reason](https://hl7.org/fhir/R5/valueset-data-absent-reason.html),
[R5 JSON representation](https://hl7.org/fhir/R5/json.html#primitive).

## What the six retained sources actually require

All six package blobs were inspected: three complete current registry records and
three PubMed EFetch XML records containing abstracts. The corpus manifest records
their exact hashes and source identities. Publication observations below are based
on those abstracts, not an assertion that full-text protocols or analysis plans
were reviewed. No new reference labels were generated.

### Vertex: the source explains the denominator difference

The NCT03525444 registry reports 405 actual enrollment. Crucially, the same record's
`/record/resultsSection/participantFlowModule/recruitmentDetails` explains that two
enrolled participants were not dosed and results concern 403 dosed participants.
PMID31697873 describes 403 participants who both underwent randomization and received
a dose. This supports a population-qualified explanation, rather than treating the
numbers as an unresolved contradiction or choosing a single winner.
[Registry](https://clinicaltrials.gov/study/NCT03525444),
[publication abstract](https://pubmed.ncbi.nlm.nih.gov/31697873/).

Additional directly retained details illustrate why a trial-wide denominator fails:

| Registry context | Counts and identity | Consequence for v2 |
|---|---|---|
| Flow period 0, milestone 0 (`STARTED`) | Placebo 203; combination 200 | Keep the milestone and period; do not silently relabel this as a universal enrollment count. |
| Flow period 0, milestone 1 (`Safety Set`) | Placebo 201; combination 202; comment attributes grouping to actual treatment received | Distinguish treatment-received grouping from other population/grouping bases. |
| Outcome 0, primary endpoint | Denominators 203/200; explicit full-analysis-set and week-4/data-cutoff criteria | The analysis population is more specific than enrollment. |
| Outcome 9, BMI z-score | Denominators 74/71; participants aged at most 20 at baseline | Do not substitute full-trial denominators for the subgroup endpoint. |
| Outcome 12, pharmacokinetics | `OG000` denotes the combination group; in outcome 0 it denotes placebo | Source hash plus `OG000` is still insufficient identity. |

These are observations from the retained
[registry results](https://clinicaltrials.gov/study/NCT03525444?tab=results), not
hand-adjudicated gold. Do not infer that 403 is the total number randomized merely
from an abstract statement about participants who were randomized **and** dosed.

**Required identity inference:** bind a result group to
`(source_content_sha256, owning_container_pointer, local_group_id)`. An outcome's
group lookup must use that outcome's `groups`, not another outcome or module.
Namespaced source-local IDs remain distinct until an explicit supported mapping
relates them. This also prevents treating `FG000`, `BG000` and `OG000` as one
automatically interchangeable arm.

### CTX112: preserve phase and source availability

NCT05643742 has one experimental arm but explicitly records allocation `NA` and
intervention model `SEQUENTIAL`. It reports estimated enrollment 120. Its phase-1
primary outcome concerns dose-limiting toxicities through 28 days; its phase-2
primary outcome concerns response through 60 months. These are separate endpoint
observations, not conflicting definitions of one primary endpoint.
[Registry](https://clinicaltrials.gov/study/NCT05643742).

`hasResults=false` is present and `resultsSection` is absent in this snapshot. A
bounded negative PubMed search is separately retained as acquisition metadata.
Neither establishes absence of conference or company results. Preserve the source
enum `NA`; do not replace it with epistemic uncertainty or infer randomization from
the generic fact that this is an interventional study.

### DCVax-L: distinguish original assignment from reported analysis

NCT00045968 combines randomized/parallel structured design with a primary endpoint
description involving external controls. The 2018 abstract reports a randomized
232/99 allocation, primary PFS and secondary OS. The later abstract describes an
externally controlled nonrandomized analysis and separately repeats the historical
randomized allocation. The same publication therefore contains both contexts;
source identity alone is insufficient without an analysis/context identity.
[Registry](https://clinicaltrials.gov/study/NCT00045968),
[2018 abstract](https://pubmed.ncbi.nlm.nih.gov/29843811/),
[later abstract](https://pubmed.ncbi.nlm.nih.gov/36394838/).

An original-design observation and a later-analysis observation can coexist. The
record does not establish the endpoint-amendment date, approval chronology or
prespecification status; those remain unresolved without suitable additional
evidence. The source's `UNKNOWN` study-status enum is itself a reported value;
it is not equivalent to a field that our parser or model omitted.

## Output design and implemented boundary

The design keeps a single case-level dossier and trial-family identity, adding
typed observation records and reusing citations instead of duplicating the trial
object for every paper. The table records the design intent; the exact implemented
contract is [observation_models.py](../../src/researchdesk/research/observation_models.py). A source may support several contexts; a context may contain several
groups, populations and endpoints.

| Component | Required content and boundary |
|---|---|
| Shared observation envelope | Stable public observation ID; trial ID; source/context ID; source reference(s) with full-content hash and exact pointer/passage; reported versus normalized value; explicit normalization rule if used. |
| Context | Source-local label and location; kind such as registry snapshot, original assignment or reported analysis, only when supported; relevant phase/period and population description. Do not invent chronology from publication order. |
| Design observation | Allocation, intervention model, masking description/roles and phase as source-reported fields, each with evidence. Preserve publication wording separately from registry enum conventions. |
| Group identity | Source hash, owning container pointer, local ID and reported label/intervention. A public alias may shorten this tuple but must resolve uniquely. Cross-source mappings are separate supported assertions. |
| Population count | Nonnegative normalized count when parseable; raw value/type; enrollment target/actual or other reported basis; population definition; group, period and endpoint/context links as applicable; units. Retain joint definitions such as randomized-and-dosed without asserting their marginal totals. |
| Endpoint observation | Source-local identity; role, variable/definition, timeframe, analysis metric/aggregation when reported; phase, population and comparison links. Distinguish source-reported prespecification from independently established timing; unresolved is allowed. |
| Availability observation | Source-scoped reported results flag/status and inspected-container presence; observed snapshot time. Separate registry posting from results elsewhere and from estimated completion dates. |
| Reconciliation issue | Linked observations; question; state (`explained_by_source`, `unresolved`, `different_context`, or `apparent_conflict`); explanation and supporting evidence; missing evidence needed. Never overwrite the original observations. |

This is deliberately more useful than copying fields: it supports an attributable
answer to why two counts or design labels differ, while retaining what the sources
actually say. It does not require patient-level data, a full FHIR implementation,
effect-size synthesis, causal grading, ontology-wide drug matching or a forecast.
Extracting published effect estimates can be a later explicitly scoped extension;
do not require it to complete these enrollment/design/endpoint cases.

### Missingness needs two layers

At the **source layer**, distinguish a present value, a present literal null and a
missing key/container. An exact pointer can validate null presence; it cannot prove
why information is absent. No literal null was observed inside the three acquired
registry `record` objects, which is a corpus observation, not an API-wide guarantee.

At the **interpretation/evaluation layer**, distinguish supported value, source-reported
unknown/not-applicable, unresolved inference, candidate omission and outside scope.
`0`, `false`, `NA`, `UNKNOWN`, null and a missing key are not interchangeable.
An absence claim should name the inspected parent/container and missing field and
be checked against retained bytes; do not manufacture a quotation for absent text.
Candidate omission is an evaluator outcome, not a source fact. A model should not
receive credit for “unknown” where a required scoped value is explicitly available.

### Public mapping, references and acceptance gates

Publish identity/location mappings before candidate outputs, without expected
values or review rationales. Provide the same mappings to all compared systems.
Freeze questions that ask for source-specific extraction and supported explanation,
without hinting at known answers. The existing broader questions can remain for
unscored development; this document and selection rationale are not candidate inputs.

Reference construction remains separate work: define assessed observations/fields,
accepted normalizations, missingness and severity rules before scoring. Prepare a
field-level evidence ledger independently of candidate outputs, then have a
different reviewer check it. Mechanical references establish mechanical agreement;
causal, comparability and prespecification judgments need appropriate independent
domain review or must remain excluded/unlabelled.

Minimum v2 acceptance examples are: the explained Vertex enrollment/dosing difference;
different safety versus analysis grouping; outcome-local `OG000`; the 74/71 subgroup
denominator; CTX112's phase-specific endpoints; and DCVax's two design/analysis
contexts with unresolved amendment chronology. Also test integer-string counts,
explicit false, missing containers, null, unknown and not-applicable independently.
These cases motivate engineering tests and reference scope; they are not yet gold.

## Access notes and unresolved work

The web extractor returned only an application shell for ClinicalTrials.gov's
dynamic definition pages. Their public policy text was read from the official
page's linked application module, without executing downloaded code; the official
API metadata was retrieved directly. The browser surface was unavailable. These
access limitations do not affect the separately retained study-source snapshots.

Open work: freeze public mappings and a narrow v2 reference/scoring scope; inspect relevant source-history/protocol material where needed;
independently review references; then run and report real comparisons under the
frozen protocol. Three selected development families cannot establish general
research quality or eliminate training-data contamination.


## Implementation qualification boundary

The v2 output model, production submission tool, benchmark selection and UI now
preserve source-qualified observations alongside legacy v1 readability. Contexts
using local groups must name the exact container owning that groups array.
Endpoint population links are reciprocal. Count normalization is explicit and
checked against a dedicated source value; availability booleans/nulls are likewise
bound without type coercion. Missing-key proofs require an existing parent object.
`inspect_source` supplies bounded navigation and exact citations for all arms.
Global dossier/source bounds include anchors and absence proofs, not just quotes.
An extraction-only dossier explicitly sets `forecast: null`.

The semantic limit is deliberate: a quoted number in prose, a normalized design
label, a population interpretation or a reconciliation still needs independent
review. Source integrity and matching text do not prove those interpretations.
The retained real-case verification is operator-authored, not a model run or a gold
reference. Final reference scope and independent adjudication remain separate gates.
