# Options-engine feasibility spike

Recorded 2026-10-05. Companion to [ADR 0002](0002-options-engine-comparison.md).
This is executed synthetic accounting evidence, not investment performance or
production qualification. No broker, paid dataset, research agent, main ledger,
or application dependency was used or changed.

## Result and recommendation

**Do not select or migrate to an options engine yet.** NautilusTrader ran a genuine
partial-fill/cancellation/physical-expiry sequence and matched independent arithmetic.
The negative cases expose integration requirements that a successful backtest alone
would miss. The [subsequent LEAN execution](lean-runtime-protocol.md#first-execution-native-tick-input-rejected)
compiled and launched the full engine, but all eight scenarios were rejected during
initialization because native options backtests do not support Tick resolution.
The [separate minute-bar controls](lean-minute-protocol.md#executed-result-2026-10-06-utc)
then completed funded ITM exercise, its identical replay and worthless OTM expiry,
matching hand arithmetic and completed-bar timing. They do not establish equivalent
tick-level fill behavior or qualify the remaining failure/assignment cases.

Keep the engine boundary proposed in ADR 0002: ResearchDesk owns evidence and authority;
one selected engine owns economic simulation. A completed, validated event batch may
be exported transactionally. Never import an engine's partially failed cache as a
committed portfolio or create two independently writable economic books.

## Pinned environment and actual installation

| Item | Observed value |
|---|---|
| Python | CPython 3.12.14 |
| Host | macOS 14.7.7, ARM64 |
| Executed engine | `nautilus-trader==2.0.0rc6` |
| Upstream tag commit | `7b766f8825b2539c5b2ac1375e9d97b41c509edb` |
| Wheel | `nautilus_trader-2.0.0rc6-cp312-cp312-macosx_11_0_arm64.whl` |
| Wheel bytes | 59,959,591 |
| PyPI wheel SHA-256 | `ca2aa24e790ef2a4251f7efced1ca8e3c8408d23b69af949a0467d6d5ae33618` |
| Temporary environment | `/private/tmp/researchdesk-options-spike-31ese_eo` |
| Installed package set | `nautilus-trader==2.0.0rc6`; no pandas/reporting extras |

The wheel installed and imported successfully. The engine's startup version information
also reported commit prefix `7b766f8825b2`. Its current documentation describes 2.x,
while an unqualified stable PyPI installation selects 1.231.0 with a different API.
The RC was selected explicitly for this experiment, not for deployment. The documented
macOS support floor is 15; this successful run on 14.7.7 is **not** a supported-platform
claim. Repeat qualification on a supported deployment platform before adoption.
[Official installation guidance](https://nautilustrader.io/docs/latest/getting_started/installation/),
[pinned release metadata](https://pypi.org/pypi/nautilus_trader/2.0.0rc6/json).

Actual commands, from the repository root unless a path is absolute:

```sh
/private/tmp/researchdesk-options-spike-31ese_eo/bin/python -m pip install --only-binary=:all: 'nautilus_trader==2.0.0rc6'
/private/tmp/researchdesk-options-spike-31ese_eo/bin/python examples/engine_spikes/nautilus_options.py --output examples/engine_spikes/nautilus-observed-2026-10-05.json
.venv/bin/ruff check examples/engine_spikes
```

For another machine, create a separate Python 3.12 virtual environment, install
[the isolated requirements](../../examples/engine_spikes/requirements.txt), and run
[the experiment](../../examples/engine_spikes/nautilus_options.py) with that interpreter.
The script checks the exact engine version. It does not import ResearchDesk.

## Frozen synthetic scenario and independent arithmetic

The contract is an unadjusted USD equity call: strike 100, premium multiplier 100,
deliverable 100 shares, expiry 2026-01-16 21:00:00 UTC. These are explicit fixture
assumptions; the test establishes expiry behavior, not American early exercise.
The synthetic venue is `XTEST`, the underlying is `TEST`, and no real security is used.

Starting capital is 20,000. A limit order buys two contracts at premium 2.00, but the
displayed ask contains one contract. The strategy cancels the remaining contract from
the fill callback. A later quote contains ten contracts; the cancelled remainder must
stay cancelled. Underlying trades move from 100 to 110 exactly at expiry.

Execution uses a cash account, explicit zero fees, `liquidity_consumption=True`, and
no latency or queue model. Zero fees isolate accounting; they do not qualify realistic
costs. The expiry uses the engine's standard settlement path, not a custom Python
implementation of exercise.

Independent expected accounting:

| Stage | Cash | Open call contracts | Underlying shares |
|---|---:|---:|---:|
| Opening | 20,000 | 0 | 0 |
| One contract filled: premium `1 × 2 × 100` | 19,800 | 1 | 0 |
| Remaining order cancelled | 19,800 | 1 | 0 |
| Exercise: strike payment `100 × 100` | 9,800 | 0 | 100 |

At the supplied terminal underlying price 110, equity is `9,800 + 100 × 110 = 20,800`.
The resulting 800 difference is a check on this invented tape, **not a strategy return**.
The engine records the option's close at zero and the shares' acquisition at strike;
therefore option realized P&L is −200 and share unrealized P&L is +1,000. Their sum
agrees with the same 800 accounting difference.

## Executed results and failure paths

Six engine runs completed their expected experiment assertions: funded ITM twice,
OTM, insufficient exercise cash, absent underlying last trade, and stale last trade.
[Retained output](../../examples/engine_spikes/nautilus-observed-2026-10-05.json)
contains actual events, cash, positions, order status and raw identifiers. The funding
case intentionally produces an engine error; “assertions passed” does not mean that
case is safe to operate.

| Case | Actual observation | Implication |
|---|---|---|
| Funded ITM | One contract filled, remainder cancelled, option closed, 100 shares delivered at 100; cash 9,800. | Matches the independent calculation, including the underlying update exactly at expiry. |
| OTM at 90 | Option closes with no shares delivered; cash 19,800, option P&L −200. | Basic worthless expiry matches arithmetic. |
| Capital reduced to 10,000 | Premium leaves 9,800. Exercise raises a negative-cash `RuntimeError`. After the error, cache inspection shows a closed option and 100 shares, but cash still 9,800. | The failed in-memory state is not a valid economic book. Reject/quarantine the whole run; do not export it or resume it as committed state. Funding obligations need admission checks and explicit failure/recovery tests. |
| Underlying quotes only | Fresh underlying quotes exist, but no last trade. Run returns without exception; the expired call remains open. | A run returning normally is insufficient. Require resolved lifecycle obligations and suitable settlement-price inputs before accepting an experiment. |
| Prior-day last trade 110; fresh expiry quotes 90 | Engine exercises at strike 100 using the old last trade; no exception. | Enforce settlement-input freshness and source policy externally. Fresh quotes do not make an old last trade a qualified settlement price. This test does not establish which real-world settlement source should prevail. |
| Identical funded replay | Normalized economic events, positions and cash match. Expiry-generated order/trade UUIDs differ. | Economic determinism is demonstrated here; stable raw lifecycle identifiers and restart deduplication are not. |

Pinned source inspection explains these boundaries: settlement reads the underlying's
cached last-trade price; missing prices defer settlement; physical delivery is derived
from instrument multipliers; settlement-generated IDs use UUIDs. This does not establish
adjusted deliverables, early assignment or transactional recovery.
[Pinned settlement implementation](https://github.com/nautechsystems/nautilus_trader/blob/7b766f8825b2539c5b2ac1375e9d97b41c509edb/crates/execution/src/matching_engine/settlement.rs),
[upstream physical-settlement tests](https://github.com/nautechsystems/nautilus_trader/blob/7b766f8825b2539c5b2ac1375e9d97b41c509edb/crates/execution/tests/integration/matching_engine.rs).

The funding result is an **integration blocker**, not an assertion that upstream promises
an atomic cache rollback after a fatal run error. The experiment adapter must treat all
post-error state as diagnostic. Ordinary callback/schema mistakes during initial harness
development were corrected before retaining results; they are not classified as engine defects.

## LEAN local feasibility, without claiming execution

The installed Docker client could not inspect the image through `docker manifest inspect`
because of an OCI media-type error. A bounded, public registry metadata request succeeded;
the failure was not lack of ARM64 support. The checked-in
[metadata inspector](../../examples/engine_spikes/inspect_lean_image.py) reproduces the
read without downloading image layers or using a QuantConnect account.

```sh
docker manifest inspect quantconnect/lean:latest
.venv/bin/python examples/engine_spikes/inspect_lean_image.py --output examples/engine_spikes/lean-image-observed-2026-10-05.json
```

| Item | Observed value |
|---|---|
| Index digest | `sha256:442c0f886cbc55403d779fa3cbd6070c192a7b8e1f2a5dcf9b570b735dc543e4` |
| ARM64 digest | `sha256:e03a90c24efc7849426fb8a00d1c643a9196c1507ae5ee52fa004f85bfb9e4c7` |
| Platform | `linux/arm64` |
| Compressed layers | 5,070,465,520 bytes; about 5.07 GB decimal |
| Image labels | LEAN 18156; .NET 10.0; Python 3.11.11 |
| Entrypoint | `dotnet QuantConnect.Lean.Launcher.dll` |
| Execution | Not pulled or run; no local `dotnet` executable found |

[Saved metadata](../../examples/engine_spikes/lean-image-observed-2026-10-05.json)
is evidence for packaging feasibility only. The 5 GB download was deliberately outside
this bounded first spike. The direct open-source engine route is distinct from LEAN CLI:
official CLI documentation requires membership in a paid organization. No login,
subscription, data purchase or claim of an authenticated run was made.
[Official CLI authentication requirements](https://www.quantconnect.com/docs/v2/lean-cli/initialization/authentication).

Source review was pinned separately to LEAN commit
`705b9551be1aaa821c7f77896a7eb8fcd07b92ee`; the image labels do not prove that commit's
identity. The default assignment source distinguishes American versus European styles,
uses a four-day American window and a 5% ITM default with an arbitrage test. Its default
exercise model emits option and physical-underlying fills with zero fees and explicitly
leaves manual OTM exercise unfinished. These defaults require comparison cases, not
assumptions of brokerage fidelity.
[Assignment source](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Securities/Option/DefaultOptionAssignmentModel.cs),
[exercise source](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Orders/OptionExercise/DefaultExerciseModel.cs),
[portfolio accounting source](https://github.com/QuantConnect/Lean/blob/705b9551be1aaa821c7f77896a7eb8fcd07b92ee/Common/Securities/Option/OptionPortfolioModel.cs).

The inspected Nautilus source carries LGPL-3.0 licensing and LEAN carries Apache-2.0.
Distribution/linking obligations need review for the eventual integration shape;
this experiment installs the package separately and does not vendor engine source.

## Next decision gate

1. Run the same funded, OTM, funding-shortfall and missing/stale-price cases through a
   pinned LEAN runtime. Add the ADR's vertical with short-leg early assignment while its
   long leg remains open; neither engine has passed that scenario here.
2. Require a fail-closed experiment envelope: explicit settlement source/freshness,
   no unresolved expired obligations, funding checks, complete lifecycle output and no export after
   engine error. Design a durable event identity/recovery boundary, then test crashes.
3. Test fees, adjusted deliverables, collateral, multiple strategies sharing capital,
   multileg execution/legging risk and corporate actions before any options admission.
   The installed Nautilus contract API has no explicit exercise-style field; this spike
   did not establish American early exercise or selective assignment through extensions.
4. Obtain one legally usable historical options slice and record its availability,
   timestamps, expired-contract coverage and rights. Synthetic lifecycle correctness
   does not establish real data feasibility or forecast skill.

No engine adoption, default risk limit, paid integration or automatic options trading
follows from this record. Research-quality evaluation remains M1's leading task;
this spike informs its future instrument and economic-accounting interfaces.
