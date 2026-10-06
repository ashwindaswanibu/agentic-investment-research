# LEAN minute-bar lifecycle controls

Frozen 2026-10-06 before executing these controls. The preceding
[tick protocol](lean-runtime-protocol.md#first-execution-native-tick-input-rejected)
failed native initialization: this source pin supports options backtests only at
Minute, Hour and Daily resolution. Preserve that experiment and its actual result.
This is a separately invented synthetic input, not an aggregation or a successful
replay of the rejected tick tape.

## Fixed first controls

Use the same LEAN commit `705b9551be1aaa821c7f77896a7eb8fcd07b92ee`, .NET 10.0.401,
full C# launcher, static metadata, cash account, normal option exchange hours,
extended underlying hours, native models and explicit zero fees. Keep fill-forward
disabled. Do not seed holdings, force exercise, adjust the calendar, set live mode
or bypass subscription checks. Runtime networking remains disabled.

Run only `minute_itm`, an identical `minute_itm_replay`, and `minute_otm` initially.
All use 20,000 starting cash, an American TEST call with strike 100, multiplier and
deliverable 100, and January 16, 2026 expiry. All prices and observations are invented.

On January 16, New York time:

| Input | Stored time | Availability / value |
|---|---|---|
| Underlying trade | 15:55:55 | 100; available at its tick time |
| Option QuoteBar | 15:55:00 | Ends 15:56:00; bid and ask OHLC all 2.00, last sizes 10 |
| Option QuoteBar | 15:56:00 | Ends 15:57:00; bid and ask OHLC all 2.00, last sizes 10 |
| Underlying trade | 15:59:55 | 100 |
| Underlying trades | 16:00:00 and 16:00:01 | 110 for ITM; 90 for OTM |

CSV bar timestamps represent interval starts. The algorithm may submit its
one-contract market buy only after receiving the first complete bar at 15:56.
Log each actual bar's start, end, period and receipt time as well as order/fill
times. Reject timing qualification if a received bar ends after receipt or a fill
precedes the first eligible bar. End-of-bar fills still depend on LEAN's native
fill model; these checks do not establish real execution latency or liquidity.
Bar last sizes cannot establish the original displayed-size partial-fill behavior.

Conditional on an actual one-contract entry at 2.00 with zero fees, independent
accounting is:

| Stage | Economic cash (settled + unsettled) | Calls | Underlying shares |
|---|---:|---:|---:|
| Entry | 19,800 | 1 | 0 |
| ITM exercise | 9,800 | 0 | 100 |
| OTM expiry | 19,800 | 0 | 0 |

At the last supplied ITM price 110, equity would be 20,800; OTM equity would be
19,800. These invented amounts test arithmetic, not a strategy return. Native
expiry, exercise or liquidation may occur at different times: retain the actual
event chronology and reconcile differences rather than changing the tape to fit.

## Verification and next boundary

Retain the exact native final status, input/configuration/result hashes, process
exit, complete observations and errors. Only a completed native engine run with
an end callback and valid time ordering can qualify terminal comparisons. Repeat
the funded run and compare economic state; do not demand equality of runtime IDs.
The runner distinguishes completed observation from the accounting verdict.

CI explicitly uses `run_lean_spike.py --suite minute`. The original `--suite ticks`
remains reproducible and is expected to fail native initialization at this pin.
Neither suite is a production options-admission gate by itself.

After genuine entry and lifecycle behavior is established, preregister the
funding-shortfall, missing/stale-trade and asymmetric-assignment cases with the
same explicit data availability. Do not expand this first control set before
understanding its result. Engine adoption, historical data qualification, broker
fidelity, spread execution and actual research performance remain separate work.

Native formats were checked against pinned
[QuoteBar parsing](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Data/Market/QuoteBar.cs)
and [serialization/names](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Util/LeanData.cs).

## Executed result, 2026-10-06 UTC

The [actual CI run](https://github.com/ashwindaswanibu/agentic-investment-research/actions/runs/37412786303)
compiled and executed this protocol at ResearchDesk commit
`07969b67932501a0cc3063cca09e32387478dc4e`. All three runs exited normally, with
both exact native final result files reporting `Completed`, a final time and no
runtime error. [Retained case records](../../examples/engine_spikes/lean-minute-observed-2026-10-06.json)
bind the input/configuration/observation hashes and native statuses. The linked
run artifact holds the full raw observations and build diagnostics.

All entries filled one contract at 2.00 with zero fees at 20:56 UTC, January 16
(15:56 New York), after delivery of the first complete option bar. Both option
bars were observed; the independent runner chronology checks passed.

| Case | Native lifecycle at 05:00 UTC January 17 (00:00 New York) | Final cash | Calls | Shares | Equity |
|---|---|---:|---:|---:|---:|
| Funded ITM | Call closes at zero; 100 shares delivered at strike 100 | 9,800 | 0 | 100 | 20,800 |
| Identical ITM replay | Same economic events and terminal state | 9,800 | 0 | 100 | 20,800 |
| OTM | Call closes at zero without share delivery | 19,800 | 0 | 0 | 19,800 |

The native OTM removal is labelled `OptionExercise` by LEAN; it is worthless
expiry/removal economically, not payment of a strike or acquisition of shares.
Do not relabel the observed midnight lifecycle as occurring at the tape's 16:00
underlying-price update. Settled plus unsettled cash matches the independent
arithmetic; terminal unsettled cash and fees are zero in these runs.

A separate reviewer checked native statuses, time conversion, entry/lifecycle
events and hand arithmetic. ITM fixture hashes, observation-receipt hashes,
economic fill events and terminal economics match across the two runs. This
finite replay does not establish restart recovery or identifier stability generally.

This closes the first funded minute-input control set. Native tick partial fills,
cancellation, funding shortfalls, missing/stale settlement inputs, short assignment,
multileg execution and broker fidelity remain unqualified. No engine adoption,
options admission, real liquidity or investment-performance claim follows.
