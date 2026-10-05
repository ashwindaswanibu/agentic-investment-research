# Frozen clinical pilot runner

Implemented 2026-10-05. This is an operator-run development harness, not a claim
that multi-agent research is better or that the clinical workflow is qualified.
It records orchestration outcomes and attribution diagnostics. It does **not**
execute the existing closed-world extraction scorer against the real corpus;
[ADR 0003](decisions/0003-clinical-reference-scope.md) explains why that would
misrepresent the current cases. Final-set execution is disabled.

## What is compared

The protocol `frozen-clinical-profile-adaptation.v1` includes three approaches:

| Arm | Available organization |
|---|---|
| `generalist` | One coordinator, with source reading/search, analysis-code creation and isolated execution, deterministic calculations, dossier creation and final submission. |
| `fixed_specialists` | The same core capabilities, with delegation to researcher, coder and reviewer roles using frozen instructions. |
| `adaptive_specialists` | The fixed arrangement plus evidence-justified specialist profiles, independent task review and exact-version activation. Profile creation is optional and consumes the same budget. |

This compares architecture packages, not a causal effect of topology alone.
Actual delegation/profile use remains visible in the traces. No arm may fetch new
external evidence, trade, qualify generated reusable tools or access another
attempt's memory. Generated-tool adaptation requires the later M2 comparison.

All arms receive the same source versions, common instructions, model setting,
tool-call budget, model-call budget, per-task turn limit and per-call output-token
limit. A benchmark-only code adapter gives the generalist real coding capability;
production role permissions are unchanged. Review cannot certify an artifact
produced by the same task. A generalist does not need to pretend its own review
is independent in order to submit a dossier.

## Freeze inputs before attempting the pilot

The input package contains:

- A `DatasetManifest` with explicit cases, sources, issuer/study-family groups,
  split membership and reference status.
- A `BenchmarkProtocol` naming the manifest hash, provider/model, common and fixed
  role instructions, repetition count and resource envelope. Metric/decision/
  stopping declarations are retained prose; they are **not executed grading or
  promotion rules**.
- `blobs/<canonical-content-sha256>.json` for each declared evidence/reference
  object. Source acquisition retains raw HTTP bytes/hashes separately. An
  artifact digest covers parsed canonical JSON, not the original HTTP bytes.

Source and reference identities, content aliases, issuer groups and trial
families may not cross development/final splits. Group mappings still require
curation; string checks cannot discover unknown subsidiaries or related studies.
An information cutoff requires an availability timestamp for the exact input
version. Acquisition and publication dates are not substitutes. These declarations
cannot establish that the model lacked prior knowledge.

Freeze a new destination after preparing an explicit protocol:

```sh
researchdesk benchmark-freeze \
  --manifest artifacts/benchmark-development/clinical-development-v1/package/dataset-manifest.json \
  --protocol artifacts/benchmark-development/pilot-protocol.json \
  --blobs artifacts/benchmark-development/clinical-development-v1/package/blobs \
  --output artifacts/benchmarks/clinical-pilot-v1
```

`pilot-protocol.json` must be prepared first; no guessed provider/model is supplied
by this command. The acquired development package is real input data, not an
already frozen model experiment. [Corpus documentation](research-benchmark-data.md)
records the three cases and their six evidence blobs.

Freezing verifies finite JSON without duplicate keys, source content hashes,
schema/split bindings, storage bounds and a self-contained regular-file layout.
Publication uses a private temporary directory and an atomic rename. Existing
destinations are not overwritten. Each JSON/blob is limited to 2 MB; total blob
content is limited to 100 MB. Symlink paths are rejected, including symlinked
parent directories. Reference files are byte-bound only: no valid gold labels,
independent adjudication or clinical score is certified by a freeze receipt.

The bundle binds the installed Python package's source tree. Any source change
requires a new bundle. It is tamper-evident input binding, not a cryptographic
signature or protection against an operator deliberately rewriting the package.

## Run and inspect

Configure the local provider/model to exactly match the protocol, then run:

```sh
researchdesk benchmark-run \
  --bundle artifacts/benchmarks/clinical-pilot-v1 \
  --output artifacts/benchmark-runs/clinical-pilot-v1 \
  --max-attempts 1
researchdesk benchmark-report --output artifacts/benchmark-runs/clinical-pilot-v1
```

The initial implementation admits the OpenAI adapter because it passes an explicit
output-token cap. The current Claude CLI adapter does not enforce that cap and is
not admitted for this comparison. Authentication is required locally; credentials
must never be placed in a protocol, artifact or chat. There is no scripted-provider
fallback in the command. Test fixtures are confined to tests.

Before execution the harness resolves a locally installed sandbox image to its
immutable image ID. It binds interpreter/platform, installed package versions,
provider timeout, sandbox timeout, lexical retrieval and image ID to the run.
Changing that environment requires a new run directory. The image must still be
available; host Python is never a fallback. Package versions do not hash every
installed dependency file. A remote model alias may also change despite its
unchanged configured name; prefer an available pinned model version.

Every case × arm × repetition is planned before execution (up to 10,000 trials
per local journal). A deterministic hash order interleaves arms. `--max-attempts`
limits this invocation, not the registered matrix. Re-running resumes running
attempts, then proceeds to planned attempts; terminal results cannot be replaced.
Each attempt has its own SQLite research store and imports only its public
evidence. References, labels and private projections remain outside agent storage.
The CLI is a single-host, single-runner design protected by an OS file lock;
distributed benchmark execution is not supported. Output directories/files are
owner-only and contain private model transcripts; they are excluded from Git.
The file-lock implementation targets POSIX hosts (Linux/macOS).

## Recovery and outcome semantics

The shared model-call meter reserves a receipt before sending a request. A returned
turn, tool calls, continuation and usage are committed before the runtime writes
its conversation checkpoint. Recovery reuses that exact cached response. An
in-flight request whose outcome is unknown is not silently retried: the attempt
retains the failure. This avoids an unrecorded second request, but cannot prove
that the provider did not bill an errored or interrupted request.

Tool calls—including delegation, review and rejected calls—consume the existing
shared case budget. A persisted start time fixes the deadline across restarts.
The elapsed limit is an admission/cancellation cutoff, not a hard real-time kill
of a remote provider: an in-flight call can overrun it, which remains visible.
Completion timing is determined from durable task/submission timestamps, so
recovering the journal later does not turn an on-time completion into a timeout.

The root must explicitly select one immutable dossier ID/hash through
`submit_benchmark_result`; later replacements are rejected. A prose assertion of
success, or merely having created some artifact, cannot complete an evaluation.
Every task must complete within the deadline for a completed attempt; child
failures remain part of the outcome. Completion still does not imply correct
claims: structural/attribution diagnostics are reported separately. All failed,
blocked, running and planned attempts remain in the report's denominator.

All three arms now receive the same `inspect_source` capability for bounded
navigation of their isolated evidence store. New task guidance requests
`clinical-dossier.v2`; final selection accepts v1 or v2 without flattening either.
V2 preserves source/analysis/population distinctions and checks structure and
attribution. It has no clinical reference scorer yet. These code/tool/guidance
changes alter the package binding and therefore require a newly frozen bundle;
old completed attempt receipts are not reinterpreted under the new contract.

Raw provider usage is retained. Missing or incomplete token counters are explicitly
counted, and dollar cost remains null without a billing calculation. Clinical
quality scores remain null. No source-reconciliation, calibration, investment
performance or architecture-superiority claim follows from this report.

## Next qualification gates

1. Implement the source-qualified reference contract, explicit scored-field scope
   and public identity conventions in ADR 0003.
2. Prepare references independently of candidate outputs; retain source passages,
   field-level rationale and unresolved domain judgments.
3. Authenticate the provider and inspect actual development traces, tool usability,
   source support, failures and resource use. Do not optimize against a final set.
4. Freeze an adequate final design and implement/qualify its grader before enabling
   final-set execution or claiming an improvement.

The surrounding [evaluation protocol](research-evaluation-protocol.md) specifies
the later quality/statistical procedure. This runner completes the narrower
reproducibility and attempt-accounting foundation.

[ADR 0004](decisions/0004-benchmark-harness.md) compares this adapter with Inspect
and LangSmith. Qualify an Inspect integration before expanding generic scheduling,
logging or graders; preserving the application runtime does not justify rebuilding
a general evaluation platform.
