# ADR 0002: Compare options engines before expanding lifecycle accounting

- Status: proposed comparison; no engine selected or migration authorized by this record.
- Recorded and sources read: 2026-10-05.
- Evidence level: local implementation inspection and primary documentation/source review.
- Execution evidence: neither external engine has been installed or run for this comparison.
- Scope: US-listed equity/ETF options, historical simulation and paper operation only.

## Context and decision criteria

The original project plan and specialist-pod design make options a principal instrument
family. They require one economic portfolio, shared capital and correlated exposure,
whole contracts, collateral, expiration, exercise, assignment and corporate actions.
Research attribution may be virtual; cash and obligations cannot be counted twice.
The initial reference capital is USD 10,000 with a larger comparison scenario, not an
approved autonomous risk policy. The initial niche is clinical-stage biotech, but the
engine interface must remain independent of a particular research specialty.

ResearchDesk's distinctive contribution is accountable agent research, evidence,
strategy development and evaluation. A complete options simulator is an additional
maintenance obligation. Compare approaches on lifecycle correctness, historical data
feasibility, reproducibility/recovery, portfolio risk, integration cost and long-term
maintenance. Do not select an engine by a feature list or simulated profit.

## Current implementation boundary

- `src/researchdesk/paper/ledger.py` is a long-only equity/ETF ledger. It has Decimal
  accounting, cash/share reservations, partial fills and idempotent event replay.
  Economic events are opening, reservation, fill and cancellation. There is no option
  contract identity, adjusted deliverable, expiration, exercise/assignment or options
  collateral lifecycle.
- `src/researchdesk/quant/scenarios.py` calculates explicit expiration payoffs for
  stocks, long options and debit spreads. Its output is deliberately non-executable;
  it excludes pre-expiry valuation, early assignment and separate-leg settlement risk.
- `src/researchdesk/quant/backtest.py` is a single-underlying daily-bar simulator with
  prefix-only policy inputs and subsequent-session execution. It rejects corporate
  action intervals rather than claiming to account for them.
- `src/researchdesk/data/quotes.py` supplies read-only stock quotes and market calendars.
  It does not supply historical option chains, adjusted-contract reference data,
  options liquidity or Greeks.

## Alternatives

### A. Extend the custom event ledger within a narrow contract

Keep transparent accounting and existing approval/store integration. Introduce typed
instrument definitions, lifecycle events and independently verified economic changes.
Admit only a precisely stated contract subset; unsupported deliverables and lifecycle
events must fail explicitly. A policy to exit before expiry does not eliminate failed
exits, trading halts or earlier assignment.

This approach has the smallest external integration boundary but makes us responsible
for exercise, assignment, contract adjustments, multileg obligations, collateral and
conservative execution assumptions. It is credible only if the supported scope and
ongoing verification burden remain bounded.

### B. Adapt an established simulation engine behind a narrow boundary

ResearchDesk retains evidence, agent permissions, review gates, mandate, research
attribution and decision lineage. An adapter consumes versioned instruments, market
events, approved intents and risk policy, and exports immutable order, fill, lifecycle,
balance and valuation events. Specify one economic authority and transaction/recovery
contract; do not maintain two independently writable economic books.

LEAN is the first candidate for a comparative spike because it exposes explicit
exercise/assignment models and option-strategy position-group buying power. This is a
research priority, not an adoption decision. Its default assignment model uses an
hourly near-expiry/deep-in-the-money heuristic; its default exercise model fills the
full quantity with zero fees. Defaults must be validated or replaced for the selected
scope. [Assignment documentation][lean-assignment], [implementation][lean-assignment-code],
[exercise][lean-exercise], [buying power][lean-buying-power].

NautilusTrader is a credible comparator for event-driven replay. Current documentation
describes option-chain replay from retained quotes/Greeks and explicit expiry-event
sequencing. Do not characterize it as lacking options support. An open upstream
feature request identifies atomic multileg package-execution gaps; this is a reported
gap to reproduce on the pinned candidate version, not a blanket claim about all
spread operations. Local Greeks treat American options as European and documented
portfolio aggregation does not apply the contract multiplier; normalization requires
explicit tests. [Options][nautilus-options], [execution sequencing][nautilus-sequencing],
[multileg request][nautilus-multileg], [Greeks conventions][nautilus-greeks].

Nautilus documentation also distinguishes state replay from live restart/reconciliation
and identifies evolving capture/replay coverage. Engine adoption does not establish
our application's recovery contract. [Event sourcing][nautilus-events].

## Proposed comparative spike

Use isolated processes and pinned engine versions/commits. No broker connection,
agent-generated strategy, production-ledger migration or options admission is needed.
Start with one underlying and two standard contracts on a clearly labelled synthetic
event tape. Prepare hand-derived expected accounting independently of either engine:

1. Buy one call with a partial fill and cancellation of the remainder; exercise the
   resulting in-the-money position into shares.
2. Enter a vertical; assign its short leg while the long leg remains open; verify cash,
   shares, remaining option exposure and resulting obligations.

Implement the smallest LEAN and Nautilus adapters that consume this tape and export
normalized events. Compare unsupported behavior, custom logic required, reproducibility
and event completeness. Agreement between engines is not an independent correctness
oracle. Retain failures and explicit model assumptions, not only successful runs.

Advance the strongest candidate through the following gates before an adoption ADR:

| Gate | Required evidence |
|---|---|
| Contract identity | Explicit strike, exercise style, expiry instant, currency, premium multiplier and deliverable. Adjusted contracts are correct or explicitly rejected. |
| Lifecycle | ITM/OTM expiry, early and one-leg assignment, exercise funding shortfall, cancellations and fees produce independently expected cash, positions and obligations. |
| Execution | Stale/missing/crossed quotes fail, displayed liquidity cannot be reused, partial fills and fees are explicit, and atomic multileg behavior is demonstrated or legging risk retained. |
| Historical correctness | As-of instrument/universe membership, expired/delisted contracts, raw underlying consistency, exchange calendars and corporate actions are checked; later data cannot enter earlier decisions. |
| Replay and recovery | Identical events reproduce economic state; interruption/restart and duplicate reports cannot double-fill, double-charge or double-settle. |
| Portfolio risk | Concurrent strategies compete for one cash/collateral pool; whole-contract sizing, pending obligations, concentration and correlated stress are visible, including after assignment. |
| Data feasibility | A legally usable historical options slice validates real ingestion and lifecycle behavior; provider coverage, missing fields, rights and cost are recorded separately from engine capability. |
| Operational fit | Reproducible pinned installation, resource bounds, supported platform, license/dependency obligations and export/recovery format are verified. |

Contract multiplier and deliverable must be distinct. OCC/OIC examples show reverse
splits where the premium multiplier remains 100 while the deliverable becomes fewer
shares; merger deliverables may include cash or different securities. Use adjustment
memos as contract-specific evidence, not a universal 100-share assumption.
[OIC contract adjustments][oic-adjustments].

## Decision and unresolved work

Retain the bounded equities implementation while completing its current operations
milestone. Do not add custom options lifecycle code before the comparison gate.
Choose adapt/adopt/extend only after recording the spike results, supported contract
subset, remaining custom logic, data feasibility and operational cost.

No external engine version has yet been selected. The cited documentation tracks
`latest` or the repository's development/default branch; a spike must pin versions,
recheck relevant source/tests and retain its exact manifests. Engine capability does
not imply affordable historical data, complete US options lifecycle fidelity, broker
equivalence, qualified autonomous risk limits or demonstrated investment returns.

## Primary sources

All links below were read 2026-10-05. Vendor documentation is evidence about the vendor
system, not proof of correct behavior in this repository.

[lean-assignment]: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/options-models/assignment
[lean-assignment-code]: https://github.com/QuantConnect/Lean/blob/master/Common/Securities/Option/DefaultOptionAssignmentModel.cs
[lean-exercise]: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/options-models/exercise
[lean-buying-power]: https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/buying-power
[nautilus-options]: https://nautilustrader.io/docs/latest/concepts/options/
[nautilus-sequencing]: https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/
[nautilus-multileg]: https://github.com/nautechsystems/nautilus_trader/issues/5218
[nautilus-greeks]: https://nautilustrader.io/docs/latest/concepts/greeks/
[nautilus-events]: https://nautilustrader.io/docs/latest/concepts/event_sourcing/
[oic-adjustments]: https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies
