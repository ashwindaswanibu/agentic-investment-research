# Frozen LEAN runtime comparison protocol

Recorded 2026-10-05, before running the new harness. This executes the outstanding
[ADR 0002 comparison](0002-options-engine-comparison.md); it does not select an engine.

## Scope and implementation

Build the open-source C# launcher from commit
`705b9551be1aaa821c7f77896a7eb8fcd07b92ee` with .NET SDK 10.0.401 on a fresh Ubuntu
runner. The reviewed source targets net10.0. No QuantConnect CLI, account, data
subscription or application database participates. External networking is disabled
for the actual engine runs after dependency restoration/build. Build logs and
resolved package metadata are retained; these isolated dependencies do not become
Researchdesk's runtime dependencies.

Copy only a new QCAlgorithm into that checkout. Keep LEAN's data feed, transaction
handler, fill, exercise, assignment, portfolio and calendar code unchanged. Set
fees to zero explicitly to isolate accounting. Generate labelled synthetic TEST
ticks in the native file format. Copy only the pinned market-hours and symbol
properties databases; generate identity map/factor files. Do not copy upstream
market-price samples, seed holdings, force assignment, change calendars or inject
an absent trade to help a case pass.

## Cases fixed before observation

The original Nautilus tape has a 100 strike American call expiring January 16,
2026. At 15:59:55 New York, the underlying trades at 100. At :56 a 2.00 option
quote displays one contract; at :57 another displays ten. The strategy places a
two-contract buy limit at 2.00 on the first quote and cancels a remainder only
after an actual partial fill. Underlying prices update at 16:00:00 and :01.

LEAN's pinned default limit model requires a later timestamp and strict price
penetration, and does not cap fills to displayed size. Consequently, the original
tape may produce no fill. Retain this **native limit case** as an execution result.
Do not replace its fill model to obtain the desired answer.

Separate **one-contract market-entry controls** use the same prices to reach the
lifecycle code without pretending to satisfy partial-fill/cancellation behavior:

| Control | Opening capital and inputs | Independent accounting / admission question |
|---|---|---|
| Funded ITM, repeated | 20,000; terminal underlying 110 | If filled at 2.00: cash 19,800, then 9,800 and 100 shares on exercise; call closes. Repeat economic state must agree. |
| OTM | 20,000; terminal underlying 90 | Cash 19,800, no shares, option closes worthless. |
| Funding shortfall | 10,000; terminal underlying 110 | Entry leaves 9,800 against a 10,000 exercise obligation. Record rejection, liquidation, borrowing or error; negative cash cannot satisfy a cash-only policy. |
| No last trade | Fresh underlying quotes at 110, no trade | Preserve which price LEAN uses. A fresh-last-trade settlement policy would reject this input regardless of engine outcome. |
| Stale last trade | Previous-day trade 110, fresh quotes 90 | Record trade/quote times and cache values. Quote-based expiry and stale-trade exercise must remain distinguishable. |

Subscribe the underlying with extended hours so the exact expiry-boundary ticks
can be inspected; keep option exchange hours unchanged. Record actual admitted
slices and cache timestamps. Scheduled expiry may occur later than the fixture's
16:00 reference; report the native time instead of relabelling it.

The final case is a **credit call vertical with asymmetric assignment**. On January
15, a margin account with 20,000 buys one C120 at ask 1.10 and sells one C100 at bid
9.90. Underlying trade/bid/ask is 110. Long bid/ask is 0.90/1.10, short 9.90/10.10.
Fresh observations continue on a five-minute grid through 15:55, allowing the native
hourly assignment evaluator to operate. No assignment is forced.

- Entry economic cash: 20,880; C120 +1, C100 −1, shares 0.
- After completed short assignment: cash 30,880; C120 +1, C100 0, shares −100.
  At underlying 110 and long mark 1.00, economic equity is 19,980.
- If held through expiry at 110: C120 expires, cash remains 30,880 and the short
  100-share obligation remains. Equity is 19,880. Only an actual cover fill may
  flatten that obligation.

Use the first completed assignment batch by event identity/time for comparison,
not whichever snapshot happens to match the expected balances. Individual callbacks
may expose intermediate state before both option close and share delivery complete.
Retain cash settlement timing, all actual fill prices/fees and subsequent liquidation.

## Evidence and stopping condition

Each isolated run retains generated input hashes, full configuration, process status,
raw engine logs, actual slices, orders/fills/assignment events and native portfolio
snapshots. A successful process exit alone is not a successful economic experiment.
Distinguish harness completion, observed behavior and our admission verdict.
The algorithm's end callback runs before LEAN sets its final status. Qualify a
terminal portfolio only against the exact native final result: `Status=Completed`,
an `EndTime`, no `RuntimeError`, a zero process exit and the retained end callback.
Keep timeout, runtime-error and partial-callback evidence separately, and attempt
the remaining cases after an individual failure. Compare replay economics only
when both runs have qualified terminal states.

Stop this component after replaying the fixed matrix, independently reconciling
results and documenting actual gaps. Neither these synthetic scenarios nor agreement
with another engine qualifies historical data, broker fidelity, atomic spreads,
adjusted contracts, collateral across strategies, durable recovery or profitability.
Options admission remains disabled until the broader ADR gates pass.

## Inspected primary sources

- [Pinned launcher project](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Launcher/QuantConnect.Lean.Launcher.csproj).
- [Native tick serialization and filenames](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Util/LeanData.cs),
  [reader](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Data/Market/Tick.cs).
- [Default fill semantics](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Orders/Fills/FillModel.cs).
- [Assignment implementation](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Securities/Option/DefaultOptionAssignmentModel.cs)
  and [existing full-engine exercise regression](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Algorithm.CSharp/OptionExerciseAssignRegressionAlgorithm.cs).

## First execution: native tick input rejected

Observed 2026-10-06 UTC, using ResearchDesk commit
`a0e36fe14f168ef41acd319ad04df7e25330e347`. The real launcher compiled successfully
with the pinned SDK and source. All eight isolated runs then exited with code 1
and native `Status=RuntimeError` during initialization. Each recorded zero orders.
The rejection was that Tick resolution is unsupported for Option securities;
the allowed backtest resolutions are Daily, Hour and Minute. No algorithm receipt,
fill, exercise, assignment or qualified terminal portfolio was produced.

[Actual workflow](https://github.com/ashwindaswanibu/agentic-investment-research/actions/runs/37411363545),
[retained native case records](../../examples/engine_spikes/lean-observed-2026-10-06.json).
The records were extracted from the job log; they retain hashes of the generated
inputs, configuration, logs and native final results. The run artifact also holds
the full build and engine diagnostics, subject to GitHub's artifact retention.
The earlier attempt failed compilation on an unqualified `Symbol.CreateOption`
reference; qualifying `QuantConnect.Symbol` fixed that adapter error before this
execution. Neither failure is reported as a successful lifecycle experiment.

Pinned source confirms that `BaseData.SupportedResolutions()` returns the restricted
option list and `DataManager` enforces it before data-permission checks. No valid
configuration enabling the frozen tick tape was identified. Do not set live mode,
modify the option resolution list or bypass the subscription check to manufacture
equivalence with Nautilus.
[Native resolution policy](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Data/BaseData.cs),
[subscription validation](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Engine/DataFeeds/DataManager.cs).

The next comparison needs a separately declared minute-bar protocol. Start with
funded ITM, its replay and OTM controls, defining bar start/end availability and
entry timing before running them. This changes the input representation and cannot
establish the original tick-level partial-fill behavior. Extend to the remaining
lifecycle questions only after verifying the native bar path. This tick protocol
and its failed result remain intact. No engine is selected or admitted to paper
options execution.
