# Inspect adapter feasibility spike

**Result, 2026-10-05:** Inspect **0.3.276** successfully scheduled a frozen
synthetic case under three arm identities and two repetitions while ResearchDesk's
existing `Runtime`, `ToolRegistry`, artifact validation and request journal ran
unchanged. This qualifies a minimal custom-solver integration route. It does
**not** admit a production adapter or a clinical/model-quality comparison.

The runnable [spike](../../examples/evaluation_spikes/inspect_runtime_spike.py),
[observations](../../examples/evaluation_spikes/observed-2026-10-05/inspect-runtime-observed.json),
[first Inspect log](../../examples/evaluation_spikes/observed-2026-10-05/first.eval),
[rescheduled log](../../examples/evaluation_spikes/observed-2026-10-05/rescheduled.eval),
and [retention checksums](../../examples/evaluation_spikes/observed-2026-10-05/retention-manifest.json)
are retained. Every case, response, source and target in those artifacts is an
explicitly fictional engineering fixture. No model was queried, no clinical
reference was graded, and no profitability claim is made.

## Qualification target and method

[ADR 0004](0004-benchmark-harness.md) identifies Inspect as the next candidate for
scheduling and standard evaluation logs, subject to retaining our existing
boundaries. Its custom solver interface permits arbitrary Python agent execution;
`TaskState` supplies the sample ID and epoch. A solver can therefore invoke our
runtime without translating our tools into a second tool system.
[Official solver documentation](https://inspect.aisi.org.uk/solvers.html)

The spike uses one `Sample` for each `(case_id, arm)` pair and Inspect's `epochs=2`.
It maps the one-based epoch to our zero-based repetition. The adapter resolves
that exact triple against the frozen manifest and the journal's predeclared
attempts. It forwards neither Inspect's full task state nor its input/metadata
to the candidate. The existing preparation path imports only the declared public
source into a new per-attempt SQLite store. The candidate's request is constructed
by the real Runtime, not by Inspect's default agent.

The deterministic provider asks real registered tools to read the source, persist
a structured dossier and freeze its final artifact ID/hash. Tool responses come
from the actual code. For `adaptive_specialists`, repetition 1, it deliberately
raises a provider error after the first source-read tool result. This tests
failure accounting; it is not evidence that the adaptive architecture performs
worse. Registry advertisements are checked for all arms, but the provider does
not delegate or create profiles. No code-execution sandbox is invoked.

Inspect runs with `max_samples=1`, `max_tasks=1`, `max_connections=1`,
`retry_on_error=0`, `fail_on_error=False`, `score=False`, `checkpoint=False`, and
local `.eval` logs. `mockllm/model` is a required framework placeholder; the
solver never calls Inspect's `generate`. ResearchDesk's serial OS lock, bounded
runtime and metered provider remain authoritative. This is deliberately a serial
feasibility test, not a concurrency or throughput implementation.

## Observed acceptance checks

| Check | Actual observation |
|---|---|
| Registered denominator | One case × three arms × two repetitions = **six** distinct journal attempts and six Inspect samples. |
| Actual outcomes | **Five** committed final dossiers and **one** deliberate failed attempt; the failed sample is retained with `sample.error`. |
| Identity | Every log sample maps to the exact case, arm, repetition and journal attempt. The observations also retain Inspect run/evaluation/sample UUIDs and final dossier IDs/hashes. |
| Store isolation | Six distinct SQLite paths, case IDs and source-artifact IDs. Each store contains exactly one case and its own task; each source retains the same frozen content hash. |
| Candidate target isolation | The planted private target is absent from all captured provider requests and candidate cases, artifacts, tasks, messages and tool records. Protected reference/report kinds never enter candidate stores. |
| Final submission | Every successful selection resolves to the exact persisted dossier content hash. No final dossier is reported for the failed attempt. |
| Failure retention | Both the journal and first Inspect log retain the one failure, with all six planned attempts still represented. |
| Terminal rescheduling | A second Inspect evaluation of the same matrix resolves the existing receipts, including the failed receipt. All six samples remain visible; **zero** additional provider requests occur. |
| Request accounting | The journal records **22 synthetic provider requests**: five four-turn successes and one two-turn failure. Their request hashes are retained. |
| Network check | A Python socket guard observed **zero TCP connection attempts** during evaluation. Installation used public package downloads. The guard is not an OS sandbox or a general native-library egress proof. |

Inspect's top-level log status was **`success` even though one sample had an
error**, because `fail_on_error=False` kept the task running. Inspect's
`stats.model_usage` was **`{}`** while ResearchDesk recorded its 22 synthetic
requests. A completed log and empty Inspect usage cannot substitute for the
registered denominator, per-sample outcomes or ResearchDesk request receipts.
These are observations of this adapter configuration, not framework defects.

The first log evaluation ID is `mf9ue5AJsEbsp4eTaiW6nW`; the rescheduled evaluation
ID is `mQ3wCMRFV6JeskaTJQqbtR`. The retained JSON and `.eval` files are the evidence,
not the console's completion line. Inspect's official log API can read both files.
[Official log documentation](https://inspect.aisi.org.uk/eval-logs.html)

## Important boundaries and integration gaps

**Targets require a trusted adapter.** `TaskState.target` is directly accessible
to custom solver code. Inspect's logs also retain each target, intentionally.
The protected sentinel is consequently present in operator-side `.eval` files,
which contain only synthetic data in this spike. Isolation was established for
the candidate-facing channels we exercised, not for an adversarial solver with
host-process access. Do not give model-generated code the solver object, log
directory or operator bundle. Search-tool and generated-code mount probing remain
unqualified by this spike.
[Task-state API](https://inspect.aisi.org.uk/solvers.html#task-states)

**The journal owns retry decisions here.** Inspect can reschedule a sample, but
the adapter returns the existing terminal outcome. A previous failure remains
a failure; it is not an opportunity to obtain a better answer under the same
attempt identity. The second evaluation tests this explicit rescheduling route.
It does **not** test `eval_retry`, `eval_set`, interrupted processes, ambiguous
requests or Inspect checkpoint recovery. Eval sets document automatic retry and
optional failed-log cleanup; do not enable those defaults as a replacement for
our receipt rules without further qualification.
[Official eval-set retry documentation](https://inspect.aisi.org.uk/eval-sets.html#retry-options)

**Runtime transcripts are not automatically Inspect model events.** This solver
records a journal-linked outcome in Inspect sample metadata/output. The actual
multi-turn messages, tool calls and request receipts remain in ResearchDesk's
isolated stores/journal. No Agent Bridge, supported SDK interception, raw `httpx`
capture or proxy metering was exercised. Inspect usage is therefore left empty,
and token/dollar totals remain unclaimed. A later adapter needs explicit transcript
export and budget parity rather than assuming the bridge sees these requests.
[Official Agent Bridge documentation](https://inspect.aisi.org.uk/agent-bridge.html)

**Filesystem configuration needs attention.** The first setup attempt failed
before any sample ran: Inspect's default trace logger tried to create its macOS
application-data directory outside the allowed temporary workspace. Setting the
supported `INSPECT_TRACE_FILE` to the private output directory allowed the run to
complete without broader filesystem permissions. The final run was launched from
the temporary directory, with no project `.env` loading. No Inspect account or
hosted trace upload was used.

The solver calls a synchronous runtime from its async body. This is acceptable
only for the deliberately serial spike. Moving to concurrent Inspect samples
requires process/thread boundaries, cancellation propagation and safe journal
ownership; simply increasing `max_samples` is not qualified. The adapter also
uses ResearchDesk's internal `_run_attempt` entry point, whose implementation is
content-bound here, not a promised public API.

## Version, environment and reproduction

The [official PyPI release](https://pypi.org/project/inspect-ai/0.3.276/) is not
yanked and declares Python ≥3.10. Release metadata and wheel checksum are retained
in [inspect-release.json](../../examples/evaluation_spikes/observed-2026-10-05/inspect-release.json).
The installed wheel was `inspect_ai-0.3.276-py3-none-any.whl`, published
2026-10-02, with SHA-256
`42849799ba4f51d272a7ca2385e8e78ea3ef911ec9a71a3054fb115bd4e78dbf`.
The successful run used Python **3.12.14** on macOS **14.7.7 ARM64**. Complete
resolved package versions are in the observations; application dependencies and
the project virtual environment were not modified.

ResearchDesk's installed Python implementation hash was
`db83724ac15644a4b1d8a245c1d48033a408aa3fd6830f85431e4e21b839574f`.
The adapter SHA-256 was
`c45c1369c07040784d090ba635536532814756c6fe082306ecbe318dc5c57347`.
The frozen [manifest](../../examples/evaluation_spikes/observed-2026-10-05/manifest.json),
[protocol](../../examples/evaluation_spikes/observed-2026-10-05/protocol.json),
[binding](../../examples/evaluation_spikes/observed-2026-10-05/binding.json) and
source/reference blobs are retained. A later source revision must create a new
bundle; do not present it as a rerun of this exact implementation.

From the repository root, the equivalent clean setup is:

```sh
spike_repo="$PWD"
spike_dir="$(mktemp -d /private/tmp/researchdesk-inspect-XXXXXX)"
python3.12 -m venv "$spike_dir/venv"
"$spike_dir/venv/bin/python" -m pip install \
  -r "$spike_repo/examples/evaluation_spikes/requirements-inspect.txt" "$spike_repo"
cp "$spike_repo/examples/evaluation_spikes/inspect_runtime_spike.py" "$spike_dir/"
cd "$spike_dir"
"$spike_dir/venv/bin/python" inspect_runtime_spike.py --output "$spike_dir/observations"
```

For the actual run the temporary root was
`/private/tmp/researchdesk-inspect-spike-ving9aim`; the successful final output is
`run-3`. Its original private journal and six per-attempt databases remain there.
The repository retains the smaller portable observations and Inspect logs.
New runs will have different timestamps and UUIDs; the asserted identities,
denominators, content bindings and request counts are the reproducible checks.

## Recommendation

Continue with Inspect as the framework integration candidate, while keeping the
custom production pilot unchanged. This spike demonstrates that we can preserve
the runtime, fresh stores, frozen inputs, exact attempt identity and retained
failures through a small solver adapter. It does not justify replacing the
journal, enabling automatic retries or claiming full ADR 0004 parity.

The next bounded qualification should test actual delegated work and reviewed
profile creation, then explicit transcript export and crash/retry reconciliation.
Only after those gates pass should Inspect take over production scheduling and
redundant custom scheduling be removed. Clinical reference and scorer admission
remain governed separately by ADR 0003.
