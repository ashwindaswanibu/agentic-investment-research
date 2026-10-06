# Engineering roadmap and acceptance gates

Updated: 2026-10-06. This is the development contract for the next stages, not a
claim of achieved research quality, investment returns, or production readiness.
It follows Ashwin's instruction to develop the system component by component,
with serious design research, explicit goals, implementation and independent review.

## Priority correction, 2026-10-06

Ashwin explicitly deferred the demo until the end and stopped further demo work.
Preserve the existing source/package, but do not spend further development effort
on demo features, hosting, publication polish or its presentation. Public HTTPS
deployment and the prior Render sign-in request are deferred. Resume showcase
work only after the core research and operation milestones below are qualified,
or if Ashwin explicitly changes this priority.

Core priorities remain M1 research usefulness first, followed by measured adaptive
specialists/tools, accountable forecasts and strategies, portfolio/options
operation, and sustained monitoring. The already-started options engine controls
are bounded dependency work for M4; they do not replace the leading research-quality
milestone. Core workbench usability supports these real workflows throughout.

## Product goal

A persistent investment research and paper operation that notices relevant
changes, creates appropriate specialists, investigates competing hypotheses,
builds and validates tools, registers forecasts, selects an instrument and
position within a mandate, then monitors outcomes and learns from its mistakes.
Options remain a principal intended instrument family. The initial domain is
clinical-stage biotech, alongside reusable quantitative research capabilities.
Daily trade count is not an objective. Measured research quality and reliable
portfolio operation are separate requirements; neither proves the other.

The distinctive engineering contribution is adaptive research with accountable
tool use and evidence. An additional agent, prompt, framework, or microservice
must solve a demonstrated failure or improve a declared metric. We will compare
against simpler alternatives and retain negative results.

## Development method for every component

1. **Charter:** identify its user-visible job, strongest useful target, scope,
   dependencies, inputs/outputs, invariants and authority. Separate the eventual
   target from the next implementable milestone.
2. **Research:** inspect primary documentation, relevant source code and papers
   for at least two credible approaches where alternatives exist. Record version,
   date, assumptions, licensing/data constraints, and what we can actually reuse.
   Reading a landing page does not complete this step.
3. **Decision:** write an architecture decision record comparing quality,
   correctness, failure recovery, operating cost and implementation burden.
   Choose build/adapt/adopt deliberately. A framework migration needs a small
   comparative spike before committing to replacement.
4. **Evaluation first:** freeze representative cases, a baseline, failure cases,
   exact acceptance criteria and measurement procedure. Keep development cases
   separate from final evaluation. Choose sample sizes for the intended claim;
   a handful of fixtures cannot establish statistical superiority.
5. **Implementation:** complete one useful path with real interfaces, persistent
   state and inspectable results. Fixtures are restricted to tests and visibly
   labelled demonstrations. Missing services produce a blocked capability.
6. **Independent challenge:** another reviewer checks the actual behavior and
   adversarial cases, including interactions with adjacent components. A second
   task using the same model does not imply independent scientific judgment.
7. **Qualification:** run relevant real integrations, failure recovery and UI
   checks; retain commands, environment, outputs, unresolved issues and evidence
   links. Fix failures before broadening scope.
8. **Promotion:** describe precisely what passed, what remains experimental,
   rollback behavior, and what future evidence triggers reconsideration. Update
   the showcase and resume only to match verified capabilities.

At each checkpoint, name the direct contribution to the product goal and the
finite stopping condition. Prefer one complete research-to-decision path over
additional infrastructure. A new abstraction, service, framework or feature
needs a demonstrated failure or measurable benefit; a plausible future use is
insufficient. Record deferred work so thoroughness does not become endless scope.

Maturity labels are **specified → implemented → verified in isolation → integrated
→ qualified for the stated use**. “Production grade” is a conclusion supported by
operating evidence, never a synonym for code existing or tests passing. We will
reduce avoidable rework, but cannot promise that components never need revisiting.
Dependency, model, source and market changes require regression checks.

## Component charters

| Component | Strongest useful target | Next milestone and acceptance evidence | Current limits |
|---|---|---|---|
| Evidence and point-in-time data | Reconstruct what was knowable at each decision; track amendments, conflicting sources, entity identities and source outages. | Retain raw sources, acquisition/publication times and hashes; replay a multi-source clinical case with a correction and missing publication. No later source enters an earlier evaluation. | Source artifacts and connectors exist; complete historical availability and entity resolution are not established. |
| Research methodology and memory | Maintain mechanisms, alternatives, uncertainties and falsifiable predictions across revisions; retrieve relevant failures as well as successes. | One clinical dossier suite with independently prepared references, negative cases, single-agent baseline, frozen outputs and field/claim error analysis. | Structured dossiers, hypothesis versions and protected extraction scoring exist; semantic correctness and quality gain are unmeasured. |
| Specialist creation | Detect a concrete capability gap, design a specialist, evaluate it, promote useful versions and retire poor ones. | Compare generalist, fixed specialist and dynamically created specialist on the same declared case distribution and budget; measure accuracy, source support, abstention, latency and cost. Promotion requires evidence appropriate to its role. | Creation, scoped permissions and reviewed activation exist; empirical specialist superiority does not. |
| Agent-generated tools | Researcher defines domain semantics; coder implements a typed tool; an independent tester challenges it; agents reuse a qualified exact version. | Nontrivial clinical or financial calculation checked against an independent implementation, boundary/property tests, malformed inputs and resource exhaustion. Regressions revoke eligibility without erasing history. | Sandboxed qualification and reuse exist. A few model-written example tests establish limited functional behavior, not correctness across the domain. |
| Durable orchestration | Resume long investigations without losing context, double committing effects, leaking protected labels or expanding authority. | Crash/restart at each persistence boundary; cancellation races, duplicate deliveries, shared budget exhaustion and slow dependencies on PostgreSQL. Compare custom runtime with a checkpointed framework before adding more scheduling machinery. | Durable tasks, leases and committed-output recovery tested; real provider end-to-end run and sustained operation still needed. |
| Forecasting and evaluation | Measure whether registered beliefs improve over credible base rates, including calibration, abstentions, resolution changes and selected/rejected ideas. | Prospective forecast registry with predeclared resolution rules; proper scoring, baseline comparison, uncertainty and retained all-attempt history. Historical extraction tests remain a different evaluation. | Server-timed binary registrations and operator resolutions are implemented; genuine prospective outcomes, calibration and the independent research benchmark remain unfinished. |
| Strategy research | Convert mechanisms into executable policies and test economic usefulness under point-in-time inputs, costs and selection bias. | Reproduce a hand-calculated case and an independent engine; chronological validation, declared search history and untouched final periods. Include cash/no-trade and simple baselines. | Daily single-asset long-only experiments exist; generated-policy historical results are diagnostics, not uncontaminated out-of-sample proof. |
| Portfolio construction and risk | Allocate scarce capital across correlated opportunities and options exposures, with hard deterministic controls independent of agents. | Versioned mandate, cash/exposure accounting, stress scenarios, correlated signals, integer positions and explained rejection. Compare underlying, option structures and no trade. | Equity cash/concentration controls exist; cross-asset allocation, Greeks, collateral and stress-policy qualification remain. Numeric autonomous limits are not user-finalized. |
| Execution, lifecycle and reconciliation | Operate a paper portfolio through partial fills, cancellations, restarts, corporate actions, expiration, assignment and reconciliation. | Qualify the authenticated equities feed; compare established engines for options. Require lifecycle golden cases and independent accounting comparison before options admission. | Bounded equities monitoring, quote/calendar/performance adapters and atomic observations are implemented and locally verified. Authenticated feed operation, options execution and live authority are absent. |
| Monitoring and reassessment | Every position has a thesis, dependencies, review times, failure/exit conditions and known data freshness; material changes trigger bounded reassessment. | Persist monitoring contracts and deduplicated source-change events; replay outages, missed events, redundant signals, expired decisions and thesis invalidation. | Worker heartbeats exist; complete continuous research and position-management loop remains. |
| Workbench and observability | Follow one decision from signal through sources, competing views, code, tests, forecast, allocation, execution and later outcome. | Inspect real runs; show gaps, blocked states, staleness and exact versions. Keyboard, narrow-screen, auth and conflict paths pass. Trace IDs connect UI actions to server events. | Inspectable workbench exists; full decision-to-outcome lineage and operational alerting remain. |
| Deployment and public showcase | A new reviewer can reproduce a meaningful workflow securely and distinguish verified results from aspirations. | Fresh checkout, locked dependencies, migration/restore drill, secret/history audit, CI, real run walkthrough, explicit limitations and verified public links. | Public source, successful remote CI and an isolated synthetic demo are available. Its combined container passed a 512 MiB / 0.1 CPU smoke and failure check; hosting account access, HTTPS deployment, migration/restore qualification and authenticated model demonstration remain unfinished. |

## Sequence and boundaries

**M0 — close the current operations milestone safely.** Finish the read-only quote
adapter, explicit mandate/control state, leased monitoring worker and honest
valuation history. This is a narrow integration and failure-recovery exercise;
it does not qualify investment autonomy. No default risk numbers silently become
an active mandate. Do not begin custom options lifecycle code during this stage.
The finite exit checklist is: inactive defaults; immutable mandates and conflicting
control updates; lease expiry and fencing; halt/cancellation races; attributable
fresh quotes with no repeated liquidity; official-session gaps; atomic ledger and
observation commit/rollback; read-only/auth boundaries; independent code review;
browser inspection. Authenticated feed verification remains a separately named
pending gate if access is unavailable. After these checks, stop extending M0.

**M1 — qualify one research workflow end to end.** Clinical evidence is the first
vertical slice: source acquisition → registered hypothesis → specialist/tool
collaboration → source-supported dossier → independent evaluation → inspection.
Establish the baseline and test set before prompt optimization. Authenticate a
real provider locally to run it; until then retain the missing integration gate.
This remains the leading product priority. The concrete evaluation design is in
[the M1 protocol](research-evaluation-protocol.md).
The [frozen pilot harness](benchmark-runner.md) now retains isolated attempts,
global call budgets and crash receipts. Three real clinical families were acquired
and import-verified. They remain unscored: [ADR 0003](decisions/0003-clinical-reference-scope.md)
identified source/analysis/population distinctions that the current reference
schema cannot faithfully represent. Source-qualified v2 outputs now preserve
these distinctions, with explicit missingness, scoped group identities and bounded
source navigation. The [bounded mechanical evaluation checkpoint](research/mechanical-evaluation.md)
now includes public scopes, private source projections, a deterministic baseline,
protected comparisons and field-level inspection. All 38 declared real-source
fields were reproduced by deterministic copying; deliberate count errors were
isolated. This verifies the instrument, not agent research quality. Independent
automated source/key review subsequently checked all 38 fields; v2 makes enum
lookups explicit and enforces the promised count length. Its separate audit receipt
does not establish expert adjudication. Authenticated model comparisons remain
unfinished; see the [updated checkpoint](research/mechanical-evaluation.md#independent-review-and-explicit-normalization-v2).
[ADR 0004](decisions/0004-benchmark-harness.md) also requires an Inspect compatibility
spike before growing custom evaluation scheduling or dashboards. The
[executed serial spike](decisions/inspect-adapter-spike.md) retained six synthetic
attempts, including one deliberate failure, and reused terminal receipts without
new requests. Transcript/budget export, interrupted-process parity and real
provider execution remain required before adopting that adapter.
Freeze the benchmark protocol before optimization: independently adjudicated
references, critical-error categories, issuer/trial-family separation between
development and final cases, repeated trials, budget-matched baselines, calibrated
human/model grading and predeclared uncertainty/comparison rules appropriate to
the intended claim. Document sample-size rationale instead of inventing a target
accuracy or treating one successful case as qualification.

Run the read-only options engine/data feasibility spike alongside M1 so unavailable
historical chains or lifecycle support surface early. This parallel design research
does not defer options discovery until prospective outcomes resolve, and does not
authorize options admission before M4.
The [executed first spike](decisions/options-engine-spike.md) found funded-expiry
agreement plus partial-error state and missing/stale-settlement-input failures in
a pinned Nautilus release candidate. The [first full LEAN runtime attempt](decisions/lean-runtime-protocol.md#first-execution-native-tick-input-rejected)
compiled successfully but rejected the tick input during initialization in all
eight runs. The [subsequent minute-bar controls](decisions/lean-minute-protocol.md#executed-result-2026-10-06-utc)
completed funded ITM exercise, replay and OTM expiry with independent arithmetic
and chronology checks. This closes the first control set, not engine selection.
Shortfall, stale inputs, assignment and broader lifecycle qualification remain.
Return to M1 research usefulness before expanding those cases further.

**M2 — measure adaptive specialists and reusable tools.** Extend M1 with a
signal-driven capability gap, domain/prompt specification, coder implementation,
independent test design, constrained activation, reuse and failure-driven revision.
Compare against the same workflow without that adaptation. Record total effort,
including failed specialists, tool development and evaluator costs.
The [queued prompt refinement and evaluation task](product-direction.md#queued-domain-specific-prompts-and-evaluation)
defines the per-task domain methods, prompt versioning and comparison requirements.
It is recorded for later implementation; it does not replace the active deliverable.

**M3 — make forecasts and decisions accountable.** Build prospective resolution,
calibration and selection history. Join evidence to scenarios, instrument choice,
portfolio constraints and explicit no-trade decisions. Backtests and extraction
accuracy cannot stand in for this evidence.
The [bounded forecast lifecycle](research/forecast-lifecycle.md) now connects exact
hypotheses to server-timed registrations, declared baselines, operator outcomes and
correction history. Per-record scores and unscored cases are inspectable. Genuine
prospective observations, independent semantic adjudication, calibration and
complete decision-to-portfolio lineage remain unfinished.

**M4 — qualify portfolio and options operation.** Use the earlier engine/data
comparison to adopt or extend only after the architectural decision. Cover contract
identity, multipliers, chains, corporate actions, settlement, exercise/assignment,
collateral, expiry and portfolio risk. Exercise realistic incidents and restore
from durable state. Paper operation remains the only trading authority.

**M5 — demonstrate sustained operation and publish.** Run the integrated workflow
for a declared observation period, report incidents and data gaps, and retain an
audit trail. Publish a clean reproducible repository and update the resume with
verified mechanisms and measured results. No fabricated returns or metrics.
Further demo, hosting and showcase preparation is deferred until this final stage
under Ashwin's explicit 2026-10-06 direction. Keep resume claims tied to verified
capabilities and measured results.

## Initial reference review

Sources checked 2026-10-05. These inform hypotheses and decisions; vendor results
are not transferable performance claims about this repository.

- [Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system): useful evidence for bounded delegation, explicit subtask contracts, tracing and the cost/coordination tradeoff. We will test whether dynamic specialists help our workload rather than assuming that more agents improve it.
- [Anthropic agent evaluations](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents): distinguish tasks, repeated trials, transcripts and actual outcomes; combine deterministic, model and human grading. Our benchmark must verify retained results and calibrate subjective graders.
- [Anthropic tool design](https://www.anthropic.com/engineering/writing-tools-for-agents): evaluate tool interfaces through actual agent use. A valid schema alone does not establish usability or efficient tool selection.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): checkpointed state and recovery offer a concrete comparison for the custom task runtime. Framework adoption does not remove idempotency or external-side-effect obligations.
- [QuantConnect framework](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview) and [LEAN source](https://github.com/QuantConnect/Lean): modular separation of research signals, portfolio construction, risk and execution is a useful engine-comparison starting point. Inspect lifecycle source/tests and reproduce cases before selecting it.
- [Alpaca latest quotes](https://docs.alpaca.markets/us/reference/stocklatestquotes-1) and [quote-size change](https://docs.alpaca.markets/us/changelog/marketdata-bid-and-ask-size-display-change): data units, feed coverage and timestamp semantics are part of correctness. The current adapter uses documented shares, preserves attribution and enforces freshness downstream.

## Evidence record for each milestone

Each milestone record must name: exact commit; source/engine versions inspected;
charter and decision; tests and real integrations executed; independently found
failures and their resolutions; reproducible demonstration; measured result with
its population/baseline; limitations; next gate. “Implemented” and “validated with
a real provider/market feed” are separate fields. Missing credentials can block
one integration without blocking useful independent engineering work.
