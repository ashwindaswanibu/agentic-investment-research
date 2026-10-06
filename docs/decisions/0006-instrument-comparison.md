# ADR 0006: Compare thesis expressions using retained prices and shared assumptions

Date: 2026-10-05. Status: implemented and locally verified; no execution or
engine-adoption decision. See the [verification record](../research/instrument-comparison.md).

## Job and boundary

An investigator needs to test whether a thesis is better expressed through the
underlying, a long option, a debit spread, or keeping cash. A directionally correct
view can still lose money through premium, timing or capped upside. The current
single-structure payoff calculator does not retain a comparison, the hypothesis,
the selected contract observations or a common capital basis.

Build one immutable, agent-callable comparison report. The investigator supplies
the alternatives and explicit expiration scenarios; software resolves saved
contract observations, calculates costs and outcomes, and retains unavailable
alternatives with their reasons. This is conditional research arithmetic. It does
not estimate probabilities, search for the best strategy, model pre-expiry marks,
grant trading authority or claim economic edge.

## Approaches considered

1. **A saved wrapper around free-input payoffs.** Small implementation, but allows
   copied prices and mismatched horizons to drift from the evidence. Reject as the
   sole interface; reuse its tested arithmetic internally.
2. **A comparison bound to hypothesis, saved chain and explicit assumptions.**
   Selected. Resolve option symbols and bid/ask prices from the immutable chain;
   retain the price times and exact input versions. Include cash and a separately
   identified stock reference. Use one budget and scenario grid for all alternatives.
3. **Adopt a full options engine first.** Required for later lifecycle qualification,
   but unnecessary for this conditional expiration calculation. The existing
   [engine comparison](0002-options-engine-comparison.md) remains open. This work
   cannot be used as a substitute for that gate.

## Contract

- One underlying, one chain expiration and one expiration scenario grid. Earlier
  research horizons require a different valuation model; do not silently equate
  an earlier target price to an expiry payoff.
- Link an existing same-case hypothesis, saved chain, and scenario evidence.
  Retain exact hashes and the information cutoff. Sources acquired after that
  cutoff cannot enter a report purporting to use only information available then.
  This check constrains recorded inputs; it cannot prove the model lacks future
  knowledge or independently validate a claimed publication date.
- Buy legs use observed asks and short legs observed bids. These are conditional
  cost inputs, never fills. Preserve independent quote and receipt times; never
  add the delay to market time. No midpoint, missing price or size is invented.
- Standard 100-multiplier/100-share terms must be an explicit research assumption.
  The chain does not verify deliverables. Reject flagged adjusted/nonstandard
  contracts; an assumption must not override a known incompatibility.
- Missing, crossed, invalid or incompatible contracts remain visible as unavailable
  candidates. No price fallback or silent removal of failed ideas.
- Stock has a separately identified reference price and source/assumption. Its
  time need not match the options chain; report the difference rather than claim
  contemporaneous attractiveness. Missing timestamps remain unknown.
  A saved prior-session daily close requires an explicit share-basis assumption.
  Preserve the dataset's raw/split-adjusted designation and corporate-action
  records; no conversion is inferred. The built-in Yahoo feed is split-adjusted,
  so its close is an observed value used under that assumption, not a qualified
  raw ask. An entirely assumed price is separately labeled and has no market time.
- Each alternative independently uses the same hypothetical capital. Size whole
  shares, single-option contracts or two-leg spreads with stated entry fees,
  carry unused cash and always include
  a cash baseline. Alternatives are not simultaneous allocations of the same money.
  Explicit research quantities are allowed; absent quantities use the maximum
  affordable amount. Display which rule was used. This permits reserve-cash
  comparisons without silently choosing an operational position-sizing policy.
- Report outcome P&L and terminal capital, expiration-only analytical loss bounds,
  and the worst supplied scenario separately. Probability-weighted figures exist
  only when all supplied probabilities sum exactly to one; label them assumptions.
- Stress entry prices at an explicit adverse basis-point change while keeping the
  base quantity. Expose cases that no longer fit the budget. Do not resize to hide
  sensitivity or automatically recommend the highest assumed expected return.
- Shared cash-return and cost assumptions are explicit. No fee, yield, liquidity,
  volatility, exercise funding or joint settlement guarantee is implied.
- The report type is ineligible for orders/backtests. Cancellation and retry
  behavior reuse existing artifact commit controls. Revisions produce new reports.

## Acceptance gates fixed before implementation

1. Independent arithmetic for stock, cash, long calls/puts, and both debit-spread
   directions agrees, including fees, integer sizing and remaining cash.
2. Identical scenarios/budget/expiry govern every candidate; no scenario probabilities
   means no probability-weighted ranking or values.
3. Base and stress calculations keep the same quantity; loss of affordability is
   visible. Known invalid terms or prices cannot be overridden by assumptions.
4. Exact hypothesis, chain and other input hashes are retained. Wrong-case,
   protected, future-acquired and mismatched-expiry inputs fail. Delayed timestamps
   survive unchanged; an old quote remains old.
5. Tool retries recover the committed report; cancellation cannot commit it. The
   execution boundary rejects it. Failed candidates remain inspectable.
6. A reproducible, explicitly synthetic example exercises the real tool path and
   inspector. Verify desktop/narrow layout, missing/unweighted results, provenance
   and adverse-cost outcomes. No fixture result is reported as investment evidence.

## Domain sources checked

[OIC long calls](https://prd-web.optionseducation.org/strategies/all-strategies/long-call)
describes premium loss, strike-plus-premium expiration breakeven and the importance
of the move occurring within the contract life. These support the payoff boundary,
not a model of earlier sale prices.

[OIC bear put spreads](https://www.optionseducation.org/strategies/all-strategies/bear-put-spread)
explains the same-expiry strike relationship, net-debit payoff, early assignment
and expiration uncertainty. Therefore joint-expiry loss bounds must not be presented
as complete operational risk limits.

[LEAN assignment models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/options-models/assignment)
separately simulate assignment through explicit models. An expiration payoff table
does not perform that simulation. The existing engine ADR governs future adoption.
