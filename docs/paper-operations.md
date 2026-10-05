# Paper operations: contract and current limits

This component connects existing reviewed equity/ETF intents to a bounded local
simulation. It does not create investment hypotheses, choose portfolio allocation,
implement options lifecycle events, or send orders to a broker. Its acceptance
scope is M0 in [the engineering roadmap](engineering-roadmap.md).

## Operator authority

Open the paper account, then use Operations to save an immutable mandate with an
explicit symbol universe, concentration/notional limits, maximum quote age,
assumed fees, pending-order limit, order/decision ages, polling interval, monetary
drawdown threshold and expiry. Every field is required; saving does not activate.
Activation selects the exact saved version. Concurrent control edits conflict and
require a refresh; the UI does not retry a conflicting command automatically.

- **Active:** admit eligible reviewed entries and exits and process pending orders.
- **Exit only:** cancel pending buys; allow reviewed sales from owned holdings.
- **Halted:** cancel all pending orders, continue observations, submit no new orders.

No mode automatically liquidates positions. Changing mandate cancels pending
orders so an order cannot silently inherit different limits. Expiration halts
execution. Order age cancels remaining quantities, including partial fills.
Cancelled research cases invalidate their pending orders. Once operations has
been explicitly controlled, manual reservation/fill endpoints cannot bypass it;
manual cancellation remains available.

The drawdown threshold compares current valid bid-marked equity with the observed
peak for that saved mandate. It latches exit-only mode, cancels buys and requires
a new saved mandate to resume entries. Clearing or reselecting an old mandate
cannot reset its latch. It is an observed entry stop, not a guaranteed loss cap;
price gaps, polling intervals and missing quotes can exceed it. It does not sell
holdings. Peak and stop status persist separately from the immutable mandate payload.

## Worker and market boundary

Configure `RESEARCHDESK_ALPACA_API_KEY`, `RESEARCHDESK_ALPACA_SECRET_KEY`, and
`RESEARCHDESK_ALPACA_FEED=iex` or `sip` locally on the worker. No credential is
submitted through the workbench. API/frontend processes need no market key.
Fresh worker status reports configuration; authentication failures are recorded
separately in the latest tick. Feed access does not activate a mandate.

```sh
researchdesk paper-worker --once
researchdesk paper-worker
```

Read-only deployments reject workers. The optional Compose paper profile runs as
a separate nonroot process with no Docker socket, model key or published port:

```sh
docker compose --profile paper build paper-worker
docker compose --profile paper up -d paper-worker
```

The adapter uses fixed HTTPS GET endpoints for stock quotes, clock and calendar.
Requests bound response sizes/time, preserve provider timestamp/coverage, and
reject missing symbols or invalid prices/sizes. Current quote sizes are shares.
IEX represents one exchange, not consolidated NBBO; SIP requires appropriate data
access. Provider “latest” is not a freshness guarantee. No subscription upgrade
or broker order call is implemented.

Freshness for trading is capped at 60 seconds and may be made stricter by the
mandate. A fill cannot predate its reservation. Repeated observations of the same
quote share one displayed-liquidity allowance across orders and polls, including
equivalent Decimal spellings. This remains an approximation: it does not model
queue position, market impact or actual broker fills. Changed quote events may
represent replenishment; no claim of realistic executable capacity follows.

## Persistence and recovery

Run one scheduled paper-worker process. The poll interval applies to that process;
active-active global cadence/rate limiting is not qualified. Fencing protects an
overlapping replacement or accidental concurrent worker, while global scheduling
remains a separate operating concern.

The worker first claims a 120-second fenced lease. Network reads occur outside
transactions. Commit locks research cases in stable order, then controls, then
the account. A control edit, replacement worker or expired lease invalidates the
old tick before effects. Ledger events, valuation observation, retained marks,
calendar coverage and tick state commit atomically. A failed commit cannot leave
a fill without its matching recorded state. Interrupted reads may retry; there
is no assertion of exactly-once remote execution.

Risk is checked against the latest locked account. Drawdown is rechecked after
fills before subsequent entries. Existing positions remain visible during feed
outages; missing marks become null valuations, never zero prices or old prices
presented as fresh. Failed data reads have stable error codes without provider secrets.
An unhandled process error leaves its lease to expire and logs a sanitized failure.

## Performance contract

Accounting uses Decimal cash, cost basis and fees. Ordinary observations are
recorded at most once a minute unless the ledger changes; closing-window sampling
uses up to 15-second intervals. Poll scheduling wakes at the official close even
when the configured regular interval is five minutes. Holidays and early closes
come from the retained provider calendar.

A qualifying closing observation occurs from scheduled close through close+120s;
its oldest held quote must be at least close−60s and cannot be from the future.
This performance-only tolerance does not relax order freshness. Marks are bid
liquidation observations, not official auction prices. Daily P&L uses the previous
actual session's qualifying observation, or initial cash only on the account's
opening exchange date. Fees already enter net P&L and must not be subtracted twice.
Fill count describes activity; it does not isolate trading skill from price moves.

The API shows seven days and at most 12,000 observations, discloses truncation,
and fetches the predecessor needed for the first displayed daily baseline before
trimming display rows. All recorded observations remain in the database. Calendar
query coverage is retained; a missing retained session or changed known calendar
blocks use rather than joining across an unknown gap. The official provider's
initial response is still a source assumption, not independent calendar validation.
`as_of` is the actual latest observation; `report_as_of` is the report time. A
stopped worker cannot leave an elapsed close labelled pending forever.

## Qualification boundaries

Synthetic adapter/accounting/worker tests verify deterministic behavior, failures,
recovery and interfaces. They do not establish market performance. The authenticated
Alpaca smoke test is explicitly opt-in with `RESEARCHDESK_LIVE_ALPACA=1`; it must
be reported separately from mocked HTTP tests. No authenticated live-feed run has
been recorded during this milestone.

The worker scans the most recent 500 intents and at most 120 monitored symbols,
requesting quotes in batches of 30. Corporate actions, dividends, external cash
flows, currencies, multi-account allocation, broker reconciliation, options,
position thesis monitors and automatic source-triggered research are not supported
by this component. Operations qualification does not imply the full investment
platform is complete.
