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

The guided mechanical evaluation checkpoint is implemented and locally verified;
independent source/key review is still pending. Do not expand that infrastructure
while the product's actual research value remains untested.

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

**Now: options-chain ingestion and contract validation.** Retain real contract
identity, expiries, strikes, bid/ask observations, timestamps and feed provenance;
make unsupported, missing or stale inputs explicit. Complete the bounded adapter,
its tests and visible research output before implementing options selection or
lifecycle accounting. Authenticated provider access is a separate qualification
dependency; fixture tests cannot substitute for an actual provider run.

Research
papers such as [RD-Agent(Q)](https://arxiv.org/html/2505.15155v1) and its
[maintainer implementation](https://github.com/microsoft/RD-Agent) are comparison
candidates, not imported performance claims or adopted dependencies. Inspect
their experiments and implementation before choosing a narrowly scoped reuse.
The ongoing [engineering roadmap](engineering-roadmap.md) supplies the component
gates, but does not authorize developing all components concurrently.
