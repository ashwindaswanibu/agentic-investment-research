# Product direction and current focus

Updated 2026-10-05 from Ashwin's explicit direction. This describes the intended
product, not capabilities or investment results already achieved.

Build a full-time investment research platform useful to Ashwin and eventually
others. Its value must come from meaningful insights and better decisions. A
resume showcase is a consequence of useful work, not the primary success measure.
The ambition is substantial sustained outperformance; that remains an empirical
hypothesis requiring prospective evidence after costs, risk and selection effects.

Agents are central to the research loop: notice opportunities and contradictions,
form competing hypotheses, identify capability gaps, create specialists, design
and implement useful tools, challenge results, revise conclusions and monitor
outcomes. More agents, tool calls or generated text do not themselves count as
progress. Compare with simpler alternatives under comparable resources.

Options are a principal intended instrument family. Research must eventually
connect a forecast of outcomes and timing to market prices, candidate structures,
scenario payoffs, liquidity, capital, lifecycle risks and a versioned mandate.
Compare the underlying and no trade as well. The option engine and data must
pass their existing qualification gate before paper admission; no live trading
authority or purchased data subscription is implied.

The user experience must make the research and decisions understandable and
pleasant to use all day. Show the current conclusion, disagreement, missing
evidence and next action before technical counters. Provide direct access to
sources, agent work, executable analyses and assumptions. A generic dashboard
with decorative activity is insufficient.

At publication, provide a working demo linked from GitHub and a short, plain
walkthrough. Distinguish live execution, recorded real runs and explicit software
fixtures. Explain what works, how it works, measured results and limits without
promotional claims. A public visitor cannot spend private credentials or control
the paper account. Hosting/service access and costs must be explicit.

Recurring research, strategy assessment, monitoring and refinement are product
capabilities implemented in this repository, with persistent state, tests and
visible records. Manual operator checks support development; they must not be
the operating process. A Codex reminder is not the platform's scheduler.
Show Ashwin meaningful functioning changes in the local preview as they pass
verification. Document agents, prompt sources, tool permissions and delegation
paths in architecture diagrams linked to the actual implementation; update those
maps alongside relevant code changes.

This is an exploratory phase. Run many distinct strategy experiments in parallel,
including frequent-opportunity strategies; do not prematurely narrow the research
to one instrument, specialty or holding period. Each strategy needs a recorded
rationale, fixed evaluation rules, attributable paper results and immutable
versions. Preserve failed candidates and the complete search history. Review
outcomes after several weeks and make revisions as new versions, without erasing
the earlier record or reusing a final holdout for tuning.

Increase learning speed through broader eligible universes, historical replay and
parallel prospective experiments. Track qualifying opportunities, entered and
completed positions, holding periods, costs, market exposure and correlated
events. An order fill, a spread leg and an independent strategy outcome are
different units. High daily activity is a research aim, not a quota that silently
relaxes a strategy's entry rules. Longer-horizon outcomes still need their stated
time to mature. Keep hypothetical strategy books separately attributable; any
combined portfolio must also obey one shared economic cash/collateral constraint.
These experiment-management capabilities are requirements, not yet a qualified
continuous operating system.

Discard weak ideas from active research when the rationale is unsupported,
evaluation is invalid, or adequate evidence contradicts the thesis. Preserve the
candidate, evidence and reason as an immutable rejection. Distinguish insufficient
evidence from evidence against a thesis. Reopening a rejected idea needs a stated
new basis; writing quality and sunk engineering effort are not reasons to keep it.

## One active deliverable

The guided mechanical evaluation checkpoint is implemented and locally verified.
Independent automated source/key review checked all 38 retained fields and found
two normalization-contract discrepancies, now corrected in a new v2 package; see
[the review and verification record](research/mechanical-evaluation.md#independent-review-and-explicit-normalization-v2).
Actual model comparisons and substantive research quality remain untested. Do not
expand evaluation infrastructure beyond resolving demonstrated failures.

The investigation overview is implemented and locally verified; see its
[verification record](research/investigation-overview.md). Findings, open
questions and evidence now precede execution counters; linked evidence can be
opened across cases. This completes that bounded page change, not the whole UX.

Automatic strategy assessment is implemented and locally verified; see its
[verification record](research/strategy-assessment.md). New experiments retain
the report automatically; existing records can receive an immutable annotation.
It reconciles recorded metrics, compares baselines and exposure, and identifies
missing validation. It does not restrict exploratory strategy ideas or establish
predictive edge. The generated architecture map covers prompts, roles and tools.

**Options-data checkpoint:** The bounded
Tradier sandbox adapter, saved expiration/chain tools, operator CLI, validation
tests and chain inspector are implemented. Preserve original quote times and
receipt times; delayed observations cannot enter the existing execution path.
See [options data verification](research/options-data.md). Authenticated provider
access is still a separate qualification dependency; fixture tests cannot
substitute for an actual provider run. Ashwin confirmed the token is unavailable
for now and asked development to continue independently. Keep authenticated
qualification pending; offline implementation can proceed, but options
selection or lifecycle tests must not be represented as validated market use.

**Hypothesis-to-instrument comparison checkpoint:** The
`compare_instruments` tool binds saved hypotheses, chains and scenario evidence
to conditional stock/options/cash comparisons. It retains fees, unused capital,
cost stress, unavailable alternatives and exact source versions. It is implemented
and locally verified across the backend, production build and browser. See
[comparison verification](research/instrument-comparison.md).
This is not an options execution engine or a measured forecasting result.

**Forecast lifecycle checkpoint:** A hypothesis can now lead to an immutable
binary forecast registered before its event window, with a stated baseline and
resolution rules. Operators append source-cited outcomes and corrections; the
workbench retains pending, abstained and unresolvable records and shows per-record
Brier loss. The same registration is available to researcher/coordinator agents.
See [the executed workflow](research/forecast-lifecycle.md). Synthetic API/browser
verification establishes workflow behavior, not actual research or forecasting skill.
Do not expand this into calibration dashboards before genuine prospective outcomes.

**Next research dependency:** qualify an actual supported model provider and freeze
the bounded development-pilot protocol before running candidates. Existing Codex
authentication was inspected, but a version-specific isolated provider boundary
was not established; see [ADR 0007](decisions/0007-model-provider-isolation.md).
Do not substitute a manual assistant-written dossier for a recorded application run.

**Data budget decision, 2026-10-05:** start with free APIs. Revisit paid data as
research evidence and confidence improve; do not purchase a subscription now.
Choose a feed whose actual coverage supports the intended evaluation. Delayed,
end-of-day and indicative observations must remain distinguishable. A promising
result using limited data is a reason to investigate further, not proof of an
executable edge. Ashwin selected **Tradier's sandbox feed** as the initial options
source: consolidated market quotes delayed by 15 minutes, with account access
and an authenticated acquisition run still to verify. See the
[free options-data decision record](decisions/0005-free-options-data.md).

Research
papers such as [RD-Agent(Q)](https://arxiv.org/html/2505.15155v1) and its
[maintainer implementation](https://github.com/microsoft/RD-Agent) are comparison
candidates, not imported performance claims or adopted dependencies. Inspect
their experiments and implementation before choosing a narrowly scoped reuse.
The ongoing [engineering roadmap](engineering-roadmap.md) supplies the component
gates, but does not authorize developing all components concurrently.

## Queued: domain-specific prompts and evaluation

Added 2026-10-05 at Ashwin's request. Todo only; keep options research integration
as the current focus. Refine prompts deliberately for each task, with relevant
domain methods and evidence, rather than relying on an expert role label.

- [ ] Audit the coordinator, researcher, coder, reviewer and dynamic specialist
  instructions; identify where task-specific expertise and decision criteria are missing.
- [ ] Use a concise task structure: objective → domain-specific method → evidence
  and tools → required output → acceptance, rejection and stopping criteria.
  Preserve existing provenance, review and tool-permission controls.
- [ ] Add relevant methods, authoritative references, examples and failure cases
  for each domain. For options research, address market-implied expectations,
  forecast horizon, volatility assumptions, liquidity, costs, lifecycle risks
  and thesis invalidation. Tailor equivalent requirements to other tasks.
- [ ] Keep prompts versioned in the codebase, retain the effective prompt/version
  with evaluated runs, and update the generated agent/prompt/tool architecture map.
- [ ] Freeze representative development and held-out evaluation cases, critical
  errors and scoring criteria before optimization. Compare current and revised
  prompts using the same model, tools and budgets, with repeated trials and
  independently checked judgments. Retain unsuccessful variants.
- [ ] Promote changes only against predeclared quality and cost criteria; add
  regression cases for observed failures. Report measured results and unresolved
  gaps. Formatting, schema validity and software tests alone do not establish
  research expertise or prompt quality.
