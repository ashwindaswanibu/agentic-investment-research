# Research quality and specialist development

Researchdesk records the work needed to evaluate a conclusion. A successful tool
call, an approving model, and a profitable historical experiment answer different
questions; none substitutes for prospective evidence of predictive skill.

## Research records

`record_hypothesis` captures the proposed mechanism, prediction, competing
explanation, falsification rule and evaluation plan. Revisions and rejections link
to the preceding immutable record. The original attempt remains in the library.
The record's creation time establishes when it was registered; a self-reported
information cutoff does not prove that the author had not seen later outcomes.

`submit_clinical_dossier` accepts the source-qualified `clinical-dossier.v2`
contract and retains compatibility with v1. V2 records source/analysis contexts,
design, population counts, endpoint definitions, availability and explicit
reconciliation. Original trial assignment and a later analysis stay separate;
enrolled, dosed, safety and endpoint populations do not become one denominator.
Local group IDs are bound to their exact owning source container. Each endpoint
and its counts must link reciprocally. Extraction-only dossiers use an explicit
null forecast; requested forecasts require real dates and a falsifiable target
or explicit abstention.

`inspect_source` navigates retained evidence by JSON pointer, with bounded child
and text pages. It returns exact hashes, raw scalar types and ready-to-use source
citations. A failed lookup is an error, not proof of absence. V2 distinguishes
present values (including permitted null), unresolved interpretation, not
applicable, and a literally absent key under an existing source object. Missing
keys do not establish that evidence is absent from a study or the literature.

Every claim names a retained artifact, full-content hash and excerpt. Count
bindings distinguish exact integer/null, explicit normalization from canonical
digit strings, and extraction from prose. Availability flags preserve exact raw
boolean/null values. Prose interpretation, normalized design labels and clinical
meaning still require semantic review. The validator checks reference integrity,
quotation/scalar presence, context boundaries and structural links; failed checks
remain in immutable artifacts. The [design review](research/clinical-observation-design.md)
records primary-source semantics and the cases that motivated these distinctions.

Dossier admission is bounded to 200 KB, 30 distinct source artifacts and 8 MB of
combined source content. Repeated citations reuse integrity and text checks; an
oversized request is rejected before unbounded source processing.

A matching quotation establishes that text appeared in a source. It does not
establish that the source is correct, that the quotation supports the claim, or
that an inference follows. The existing independent `review_artifact` workflow
binds a review to the exact dossier inspected. Clinical dossiers cannot authorize
paper orders.

## Compare extraction quality against a baseline

The **legacy v1** operator path can compare two frozen dossiers against an independently prepared
`ExtractionReference`. The reference declares a complete comparison scope and
uses stable trial, arm and endpoint IDs. The deterministic scorer measures
field-level precision, recall and F1, retaining missing, unexpected and incorrect
values and distinguishing critical errors. This is a factual extraction test;
it does not grade investment reasoning, forecast calibration or clinical efficacy.
It rejects v2 instead of silently flattening source-qualified observations. The
v2 assessment scope, evidence ledger and independently checked references remain
unfinished; no real clinical quality score is reported.

```sh
researchdesk evaluate-extraction \
  --case-id CASE_ID \
  --candidate-id CANDIDATE_DOSSIER_ID \
  --baseline-id BASELINE_DOSSIER_ID \
  --reference /local/path/independent-reference.json \
  --key UNIQUE_EVALUATION_KEY
```

Prepare labels independently and freeze candidate and baseline outputs before
examining errors. Use `researchdesk.research.ExtractionReference.model_json_schema()`
for the reference schema. The CLI retains exact input hashes and the full paired
report; the operator can inspect it in the workbench.

References and detailed error reports are excluded from agent reads, retrieval,
generated-code inputs and delegation. Evaluation is an operator operation and
is not registered as a model tool. This access boundary cannot remove a model's
prior knowledge or prevent an operator from leaking labels through a task brief.
Repeated tuning against released errors requires a fresh final evaluation set.

One case is a diagnostic, not a population estimate. A credible benchmark needs
multiple independently labelled cases, a declared sampling procedure, difficult
negative examples, a fixed baseline and reported uncertainty. Synthetic test
fixtures in this repository verify the software; they are not measured research
performance.

## Specialist creation and reusable tools

The coordinator can commission a researcher to specify a domain specialist's
mandate, prompt, evidence standards and output contract, and a coder to implement
missing calculations. A specialist proposal cites the observation that motivated
it and declares a subset of existing researcher tools. Independent review applies
to the exact specification. Activation preserves the specification and review
versions, and delegated tasks receive the profile's instructions and tool scope.
The server enforces permissions even if the model requests an unlisted tool.

New executable research tools use immutable code and a declared input contract.
A reviewer supplies test cases for the exact version; qualification executes those
cases in isolated containers and retains actual outputs. Invocation requires the
passing qualification and its exact code/specification bindings. Generated tools
have no host access, network, broker credentials or authority to change evaluation
and risk controls. Results remain research artifacts.

Reviewer acceptance establishes that a profile was reviewed. Passing tool tests
establishes the declared computational behavior on those cases. Neither makes a
specialist empirically better than a baseline. Domain-quality comparisons and
future outcomes must supply that evidence before claiming superior judgment.

## Remaining investment validation

Continuous source monitoring, prospective forecast resolution, options lifecycle
accounting and portfolio allocation remain separate work. A bounded paper worker
can now consume reviewed equity intents under an explicit operator mandate, with
fresh quotes and monitored accounting. This does not close the full autonomous
research-to-portfolio loop or demonstrate alpha. Follow the staged acceptance
gates in [the engineering roadmap](engineering-roadmap.md).
