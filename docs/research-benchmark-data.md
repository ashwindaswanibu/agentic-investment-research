# Clinical research development corpus

Acquired: **2026-10-05, 14:06:49–14:09:09 UTC**. Status: three-family development
corpus, not a final benchmark. No candidate models have been scored on these data,
and no independently adjudicated clinical reference has been prepared.

This implements the acquisition stage of the
[research evaluation protocol](research-evaluation-protocol.md). The selection is
purposive and small: one comparatively straightforward randomized study, one
one-arm study without posted registry results, and one family requiring source-
and analysis-specific interpretation. It is not representative of clinical
research, biotech issuers, treatment areas or investment opportunities.

## Selected cases

| Development case | Sponsor and trial family | Retained sources | Intended challenge |
|---|---|---|---|
| `development-vertex-vx445` | Vertex Pharmaceuticals Incorporated; VX17-445-102 | [NCT03525444](https://clinicaltrials.gov/study/NCT03525444), [PMID31697873](https://pubmed.ncbi.nlm.nih.gov/31697873/) | Extract randomized design, treatment/placebo arms and the week 4 primary endpoint. Preserve different population denominators rather than treating all counts as interchangeable. |
| `development-crispr-ctx112` | CRISPR Therapeutics AG; CTX112 in B-cell malignancies | [NCT05643742](https://clinicaltrials.gov/study/NCT05643742), retained negative PubMed search | Extract phase-specific endpoints and distinguish estimated enrollment, recruitment status and absent posted registry results. |
| `development-northwest-dcvax-l` | Northwest Biotherapeutics; protocol 020221/DCVax-L | [NCT00045968](https://clinicaltrials.gov/study/NCT00045968), [PMID29843811](https://pubmed.ncbi.nlm.nih.gov/29843811/), [PMID36394838](https://pubmed.ncbi.nlm.nih.gov/36394838/) | Preserve source versions and distinguish initial randomization from later externally controlled analysis; identify endpoint changes without inventing an amendment chronology or efficacy judgment. |

### Vertex: straightforward extraction still needs population definitions

The acquired registry contains `RANDOMIZED`, `PARALLEL`, `QUADRUPLE`, actual
enrollment 405, two arms and `hasResults=true`. The primary outcome is change in
percent-predicted FEV1 from baseline at week 4. The publication abstract describes
403 participants who were randomized and received a dose. These are source-
specific population statements, not a reason to choose one unqualified number
or automatically declare a source wrong. The full registry results section was
retained, but protocol/SAP PDFs referenced by the registry were not downloaded.
[Registry](https://clinicaltrials.gov/study/NCT03525444),
[publication](https://pubmed.ncbi.nlm.nih.gov/31697873/).

### CTX112: one arm does not mean the registry design enum is SINGLE_GROUP

The acquired record lists one experimental arm, allocation `NA`, intervention
model `SEQUENTIAL`, open-label phase 1/2 design, estimated enrollment 120 and
`hasResults=false`. Its two primary outcomes apply to different phases. The
record therefore supports a one-arm/missing-registry-results case without
rewriting its structured design into a different category.
[Registry](https://clinicaltrials.gov/study/NCT05643742).

The actual connector query `NCT05643742 OR CTX112`, limit 3, returned zero PubMed
records. This means only that this bounded query returned no records at
acquisition. It does not establish that there are no conference presentations,
company disclosures, differently indexed publications or results elsewhere.
Estimated completion dates are not asserted public-readout dates.

### DCVax-L: endpoint and comparator context across versions

The retained 2018 publication abstract describes progression-free survival as
primary and overall survival as secondary. The later publication describes an
externally controlled nonrandomized overall-survival analysis. The current
registry combines structured randomized/parallel design fields with a primary
overall-survival endpoint referring to external controls. This supports a real
source-reconciliation case: initial allocation and the later reported analysis
must remain distinct. The current registry also lists estimated enrollment 348
and status `UNKNOWN`, with last-known status active/not recruiting.
[2018 publication](https://pubmed.ncbi.nlm.nih.gov/29843811/),
[later publication](https://pubmed.ncbi.nlm.nih.gov/36394838/),
[registry](https://clinicaltrials.gov/study/NCT00045968).

This corpus does **not** establish the exact amendment date, approvals,
prespecification, validity of the external control selection, or clinical
efficacy. No historical registry version, complete protocol/SAP or independently
reviewed causal assessment was acquired. Those questions remain outside the
mechanical reference.

## Acquisition and retained files

Production connector functions actually called:

- `researchdesk.data.clinical.get_trial` for all three registrations.
- `researchdesk.data.clinical.search_pubmed` for PMID31697873; for
  `NCT05643742 OR CTX112`; and for `36394838[PMID] OR 29843811[PMID]`.
- `researchdesk.data.evidence.fetch_evidence` for each publication's official
  NCBI EFetch XML. The bibliographic search connector alone does not return
  abstracts; EFetch supplies the retained abstract text.

Each registry was requested at
`https://clinicaltrials.gov/api/v2/studies/{NCT_ID}?format=json`.
Each publication was requested at
`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={PMID}&retmode=xml&tool=researchdesk`.
Exact encoded ESearch/ESummary URLs are retained in the request manifests.

The acquisition scripts wrap the existing `evidence.request_bytes` function to
save its successful raw response before the normal connector parses it. No
connector source code was modified. The frozen successful acquisition comprises
**11 responses, 289,628 raw bytes**: three registry records, three publication
XML records and five supporting search/summary responses. Six sources are
assigned to the three cases; search metadata is retained separately.

Local, gitignored paths relative to the repository:

```text
artifacts/benchmark-development/
  acquire_registry.py
  acquire_publications.py
  assemble_development.py
  package_development.py
  registry-20261005T140649Z/
  publications-20261005T140858Z/
  clinical-development-v1/
    acquisition-manifest.json
    integrity.json
    NCT00045968.projection.json
    NCT03525444.projection.json
    NCT05643742.projection.json
    PMID29843811.abstract.json
    PMID31697873.abstract.json
    PMID36394838.abstract.json
    package/
      dataset-manifest.json
      sources.json
      package.json
      blobs/<canonical-content-sha256>.json
```

Raw files have corresponding provenance containing requested/final URL,
retrieval time, content type, byte count, redirects and SHA-256. Connector
outputs and transformations have separate hashes. The registry raw JSON was
checked for equality with the connector's parsed record; publication XML was
parsed and checked to contain exactly the requested PMID. All 11 successful raw
response hashes were recomputed from disk.

The acquisition-manifest file SHA-256 is:
`b5898b05a96ee7d8dfa0b5dd34c54bc5a63d135c327142c0047e4ac34a94d2e2`.
It is an acquisition manifest, separate from the schema-validated
`DatasetManifest` in `package/dataset-manifest.json`. The latter contains three
**unlabelled, extraction-only development cases**, six evidence sources and no
reference artifacts. Its canonical SHA-256 is:
`2113168365543dc478d6490515b0d1deb668e9df1f4b50d59534f2eb7b1c5ba7`.

Package artifact IDs use `sha256:<canonical-content-hash>` as explicit immutable
blob identities, not invented existing database rows. `sources.json` supplies
each blob path, ordinary `evidence` artifact kind, title, provenance metadata,
public URL and acquisition timestamp. Blob contents are the exact connector
outputs, encoded using the store's canonical JSON convention. An importer must
retain a mapping from these package identities to actual store artifact IDs.
The manifest was reloaded through `DatasetManifest`, and all six canonical
content bindings were verified. No reference/projection artifacts enter this
candidate-visible package.

| Primary source | Raw response SHA-256 |
|---|---|
| NCT03525444 | `af42ed5ddf49813dd3f5de37b3e10211b2a7d3b9958c5b90f93ccc6e530631e6` |
| NCT05643742 | `d1e29c24fd243185006b2fec7a400cd9efa4093cec9a15a82323879e839891f5` |
| NCT00045968 | `cff366b2f21f1ca1fb6b61581b4c0e400511fec7c1899d8976be441770b0f444` |
| PMID31697873 | `287f5c798333fc47c2e63aeaf1280766e201df4de5b5482ace6d6cbf98989f2b` |
| PMID29843811 | `c9f0ebf98e06adca8dd9de5571b7fddf82764b84c48e521760cc47cdc7a89ab9` |
| PMID36394838 | `d53fc5e96bf0615062e4db70f773b1514d9cc889af16d5da1d4e0e1b1d0c62aa` |

Initial acquisition failures remain recorded: sandbox DNS failure; a partially
successful PubMed pass that encountered HTTP 429; and PubMed HTML HTTP 203
responses rejected by the connector. The successful retry used official EFetch
XML and conservative 1.1-second request spacing. Failed attempts are excluded
from the frozen successful-source manifest, not represented as valid evidence.

## Reference status and permitted interpretation

Each `registry-mechanical-projection.v1` file copies ten declared JSON-pointer
values: trial ID, sponsor, study type, phases, design, enrollment, status, arms,
primary outcomes and registry-results flag. It makes no semantic reconciliation,
inferred-date or model-generated judgment. It is a **programmatic registry
projection**, not independently adjudicated gold and not a complete reference
for the full clinical dossier schema. Publication abstract files are likewise
document transformations, not labels.

The dossier validator now supports exact JSON-pointer citations of retained numeric,
boolean and null values, so registry enrollment counts and `hasResults` can be
attributed directly. The excerpt must equal the complete canonical JSON spelling
used by artifact hashing, such as `405`, `false` or `null`; missing fields,
containers and nonfinite numbers do not qualify. Existing text-quotation matching
and full-artifact hash checks remain in force. This verifies source presence, not
whether a clinical claim follows or conflicting sources have been reconciled.

[ADR 0003: clinical reference scope](decisions/0003-clinical-reference-scope.md)
records the proposed, **unimplemented** source-qualified reference contract and
independent-review gates. In particular, total or analyzed enrollment must not be
coerced into a planned per-arm count, and initial trial design must remain distinct
from a later analysis. The current closed-world extraction scorer is not an
appropriate quality measure for these broad reconciliation questions without a
reference and schema that faithfully represent the declared scope.

All cases are development-only and extraction-only. The issuer and trial-family
IDs in the acquisition manifest must be excluded from a future final holdout;
splitting their documents into different sets would leak the same family.

`historical_as_of=false` and `information_cutoff=null` are deliberate. Exact
source-version availability has not been independently established before
acquisition. Registry update dates and publication dates are retained source
attributes, not proof that these current API bytes existed at a past decision
time. Training-data contamination remains possible, especially for these
well-known studies. This is current-source factual research development, not
prospective forecasting or an uncontaminated historical trading evaluation.

Only public study-level records, bibliographic metadata and publication abstracts
were acquired; no patient-level or private clinical data were requested. This
public document contains identifiers, source links and provenance summaries.
The acquired source bytes stay in the ignored local artifact directory.

## Next gate

The real package was imported through the pilot runner's `_prepare` path into
three isolated temporary SQLite stores: all six hashes and source mappings
matched, repeated import was idempotent, and no projections, labels or other
cases' evidence entered a store. The ignored receipt is
`artifacts/benchmark-development/clinical-development-v1/import-verification.json`.
This ingestion-only check made no model or network requests; temporary stores
were removed. It is not a model experiment or quality result.

Prepare
and independently check references appropriate to the chosen extraction scope
using [the source-qualified reference gates](decisions/0003-clinical-reference-scope.md);
keep unresolved clinical judgments unlabelled. Freeze any revised runtime
manifest and the comparison protocol before scoring.
A real authenticated provider run, independent adjudication and any comparative
quality measurement remain outstanding.
