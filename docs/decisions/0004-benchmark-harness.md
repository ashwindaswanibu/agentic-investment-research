# ADR 0004: Keep a thin runtime adapter; qualify Inspect before expanding the harness

- Status: retain the implemented local diagnostic pilot; framework integration is
  proposed and has not been installed or executed.
- Review date: 2026-10-05. Primary documentation and source only.
- Reviewed versions: Inspect's official changelog lists **0.3.276**, dated
  2026-10-02; LangSmith Python SDK **0.12.2** was checked against its release and
  tagged evaluation-runner source. Documentation pages are rolling, not immutable
  release specifications. These are review targets, not project dependencies.
  [Inspect changelog](https://inspect.aisi.org.uk/CHANGELOG.html),
  [LangSmith release](https://github.com/langchain-ai/langsmith-sdk/releases/tag/v0.12.2),
  [tagged runner](https://raw.githubusercontent.com/langchain-ai/langsmith-sdk/v0.12.2/python/langsmith/evaluation/_runner.py).

## Decision

Retain the [frozen pilot runner](../benchmark-runner.md) for its current narrow
purpose: exercise Researchdesk's existing
[Runtime](../../src/researchdesk/agents/runtime.py) and
[ToolRegistry](../../src/researchdesk/agents/registry.py) under frozen inputs,
isolated stores and explicit attempt accounting. Do not grow it into a general
evaluation platform. **Inspect is the preferred next integration candidate** for
scheduling, standard logs, inspection and scorer execution, subject to the parity
gate below. LangSmith is a viable optional experiment-analysis service, but does
not remove the need for our runtime, isolation or request-accounting adapter.

This decision does not establish framework superiority from measurements. No
framework integration, throughput comparison or real-corpus quality comparison
was run for this review. The present blocker to quality claims is the
[source-qualified reference contract](0003-clinical-reference-scope.md), not the
choice of scheduler.

## What the alternatives actually support

| Requirement | Inspect AI | LangSmith evaluation |
|---|---|---|
| Repeated trials | `epochs` repeats samples; tasks combine datasets, solvers and scorers. Our case/arm/repetition identity and paired analysis still need an explicit mapping. [Tasks](https://inspect.aisi.org.uk/tasks.html) | `num_repetitions` reruns both the target and evaluators. `max_concurrency` controls threads or concurrent async examples; this is scheduling, not a model-call budget. [Experiment configuration](https://docs.langchain.com/langsmith/experiment-configuration) |
| Hidden targets | Dataset `input` and grading `target` are separate; metadata and files are additional channels. This API separation does not prove labels cannot leak through custom tools, prompts or mounts. [Datasets](https://inspect.aisi.org.uk/datasets.html) | The tagged runner passes inputs and optionally attachments/metadata to the target, separately from reference outputs used by evaluators. Labels placed in those input channels would still leak. [Runner source](https://raw.githubusercontent.com/langchain-ai/langsmith-sdk/v0.12.2/python/langsmith/evaluation/_runner.py) |
| Per-sample isolation | Each sample gets its own configured sandbox instance. That does not automatically isolate our host-side database, retrieval, credentials or custom-agent state; those require the adapter. [Sandboxing](https://inspect.aisi.org.uk/sandboxing.html) | The reviewed SDK schedules ordinary target callables in threads/tasks. That path provides no separate process, database or filesystem by itself; create a fresh Researchdesk attempt store and retain its code sandbox. This is a conclusion about this execution path, not a claim that LangSmith offers no other sandbox product. [Experiment configuration](https://docs.langchain.com/langsmith/experiment-configuration) |
| Model/tool budgets | Sample/scoped time, token, message, turn and cost limits exist; custom limits are supported. Per-call `max_tokens` differs from total token limits. A recorded turn follows model retries/fallbacks, so it is not our reserved-request count. Cost limits require configured rates. Our global tool/request ledger must remain authoritative until equivalence is tested. [Limits](https://inspect.aisi.org.uk/setting-limits.html) | The reviewed `evaluate` runner exposes repetitions/concurrency rather than our global model/tool-call envelope. Budget enforcement stays inside the target adapter, including child tasks and failures. This is a source inspection finding, not a blanket absence claim about the platform. [Runner source](https://raw.githubusercontent.com/langchain-ai/langsmith-sdk/v0.12.2/python/langsmith/evaluation/_runner.py) |
| Restart and retry | Eval sets reuse completed samples and retry failures; failed logs may be cleaned after recovery unless configured otherwise. This is different from refusing to resend an ambiguous paid request. [Eval sets](https://inspect.aisi.org.uk/eval-sets.html) | The documented failed-example retry workflow reruns unsuccessful examples and illustrates `error_handling='ignore'`. We must retain failed attempts and cannot adopt that recipe unchanged. API-call caching is not a durable attempt journal. [Retry guide](https://docs.langchain.com/langsmith/evaluate-with-retry), [caching](https://docs.langchain.com/langsmith/experiment-configuration) |
| Logs and graders | Structured `.eval`/JSON logs and log APIs provide a mature analysis surface. Task scorers can be rerun on retained logs. [Log files](https://inspect.aisi.org.uk/eval-logs.html), [tasks](https://inspect.aisi.org.uk/tasks.html) | Targets may be whole application functions; custom evaluators and experiment views are supported. The SDK's default error policy is `log`; keep it, and separately retain our complete attempt matrix. [Evaluation quickstart](https://docs.langchain.com/langsmith/evaluation-quickstart), [runner source](https://raw.githubusercontent.com/langchain-ai/langsmith-sdk/v0.12.2/python/langsmith/evaluation/_runner.py) |

Inspect's checkpointing documentation explicitly requires its **development
version** on the review date. It describes agent state and selected sandbox files,
not arbitrary running processes or external side effects; custom agents need
integration. Do not assume that installing 0.3.276 provides qualified checkpoint
recovery for Researchdesk. [Checkpointing](https://inspect.aisi.org.uk/checkpointing.html)

## Local data and accounts

Inspect documents local installation, local evaluation and local log files.
There is no Inspect service-account step in that workflow; model-provider access
is separate. Local datasets and logs can remain local, while the configured
provider receives whatever the agent sends. A sandbox network policy does not
constrain host-side provider or tool requests.
[Getting started](https://inspect.aisi.org.uk/index.html),
[logs](https://inspect.aisi.org.uk/eval-logs.html),
[sandbox configuration](https://inspect.aisi.org.uk/sandboxing.html).

LangSmith's Python `upload_results=False` mode suppresses experiment, application
and evaluator trace uploads. Use materialized local examples rather than hosted
dataset names; the documentation's example clones a remote dataset and therefore
is not an offline demonstration. An account-free/no-egress adapter has not been
qualified here. [Local evaluation](https://docs.langchain.com/langsmith/local)

Hosted LangSmith uses an account and API key. Self-hosting its service/UI is an
Enterprise add-on requiring a licence, distinct from running the SDK locally.
No account, upload, subscription or new dependency is required by this decision.
[Account setup](https://docs.langchain.com/langsmith/create-account-api-key),
[self-hosting](https://docs.langchain.com/langsmith/self-hosted).

## Why retain any custom code?

Our useful custom boundary is small in responsibility, even though its current
implementation spans several modules:

- [Manifest schemas](../../src/researchdesk/research/benchmark_models.py) and
  [bundle validation](../../src/researchdesk/research/benchmark_bundle.py) bind
  exact source/reference content, issuer and trial-family splits, chronology,
  protocol and implementation. Freezing reference bytes does not certify labels.
- [Attempt preparation](../../src/researchdesk/research/benchmark_runner.py)
  imports only the case's public evidence into a fresh store. Its benchmark
  registry gives all arms the same core analysis tools while preserving production
  role permissions. The comparison concerns declared architecture packages,
  including profile adaptation, rather than topology alone.
- [The journal](../../src/researchdesk/research/benchmark_journal.py) plans every
  case/arm/repetition, meters requests across child tasks, caches completed
  responses for exact-turn recovery, rejects changed requests and retains failed
  or indeterminate calls. An ambiguous request is not silently sent again. This
  sacrifices automatic recovery; it does not guarantee exactly-once provider
  execution or prove that an interrupted call was not billed.

Preserving that behavior does **not** require rejecting Inspect. Its Agent Bridge
explicitly supports custom agents and third-party frameworks. However, the Python
bridge intercepts supported provider SDKs; our
[provider adapter](../../src/researchdesk/agents/providers.py) uses raw `httpx`.
Automatic metering/transcript capture cannot be assumed. Qualify an explicit
adapter or supported proxy route without replacing the production runtime.
[Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html)

The custom runner remains a maintenance risk: it owns crash semantics, private
files, attempt ordering, environment binding and denominators. Its OS lock and
SQLite journal support one local runner, not distributed workers. Its elapsed
deadline is an admission/cancellation boundary, not a hard kill of every remote
request. It reports operational and attribution diagnostics, leaves quality and
dollar cost unclaimed, and disables final-set execution. Those limits are
documented in the [runner contract](../benchmark-runner.md).

Building another generic retry scheduler, grader catalogue or evaluation dashboard
would be unnecessary duplication. Neither framework supplies our independently
checked clinical references or turns quote presence into factual correctness.

## Bounded next qualification and replacement gate

Before expanding the custom scheduler, run one pinned Inspect adapter spike around
the existing Runtime, initially with deterministic test providers and then a small
explicitly budgeted development pilot. Do not add both frameworks at once.

1. **Behavior parity:** compare frozen source IDs/hashes, rendered instructions,
   tool schemas/arguments/results and provider continuation across all three arms.
   Keep one fresh store per repetition and preserve the final dossier ID/hash.
2. **Isolation:** plant protected-label sentinels and probe read/search tools,
   memory, code mounts and exported logs. No candidate-visible channel may expose
   references, private projections or another attempt's state.
3. **Budget parity:** prove shared request/tool counts include delegated work,
   rejected calls and failures. Verify per-call output caps, timeouts and raw usage
   on the actual provider adapter. Unknown usage/cost stays unknown.
4. **Crash parity:** interrupt before dispatch, during an ambiguous request,
   after response persistence and during tool execution. Exact-turn recovery may
   reuse its receipt; an independent repetition may not reuse another trial's
   response. Retain every failure and disable retry cleanup that loses evidence.
5. **Reporting parity:** reconcile the full registered attempt matrix with logs,
   outcomes and graders. Test cancellation and limits without dropping them from
   denominators. Freeze all effective overrides and framework/provider versions.

If these pass, let Inspect own scheduling and standard evaluation logs while
retaining only source binding, runtime adaptation and any receipt guarantees it
does not replace. Remove redundant custom scheduling in the same change. If they
fail, record the precise unsupported guarantee and keep the pilot bounded. The
independent reference/scorer gate in ADR 0003 is required under either architecture
before publishing quality comparisons.
