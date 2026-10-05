# Free options data: Tradier sandbox selected

Date: 2026-10-05

Status: Ashwin confirmed a free-only budget and selected Tradier. Initial feed:
Tradier sandbox, with market data delayed by 15 minutes. Account access and
authenticated acquisition remain unverified. The adapter, tools and inspector
are implemented; see [verification](../research/options-data.md). No account,
subscription or real-feed qualification is claimed by this record.

## Decision

Start with free APIs and improve data coverage as research evidence and
confidence in strategies develop. Keep options-chain ingestion and contract
validation as the single active deliverable. Use Tradier's sandbox market-data
API for the first options adapter. This resolves provider/feed selection; the
agent-facing interface is now implemented as expiration discovery followed by
one-underlying/expiry acquisition with purpose and immutable case-source bindings.

Existing Alpaca code retrieves equity quotes. It does not establish Alpaca as
the chosen options provider. The original planning documents leave providers
open and distinguish forecast evaluation from investment performance.

## Selected provider and access dependency

Implement Tradier's sandbox feed as the initial options source. Its
documentation describes options chains and quotes from a consolidated feed
delayed by 15 minutes. Use it to inspect actual quoted spreads and collect
forward observations at no API subscription cost, subject
to access eligibility and verification. Current onboarding documentation ties
API tokens to a Tradier account; do not assume an anonymous endpoint or create a
brokerage account for the user. Sandbox Greeks and delayed streaming are not
available.

Account setup/token provisioning and a successful read-only acquisition are
remaining integration dependencies. The provider decision does not enable
broker order submission, authorize a paid subscription or qualify simulation
fills. The first adapter only reads market data and saves research evidence.
Ashwin subsequently confirmed token setup is unavailable for now and asked
development to continue without it. Keep provider qualification pending while
completing independent implementation and explicitly synthetic verification.

## Alternatives considered, not selected

ThetaData's free end-of-day endpoint was considered for a narrower research
milestone if Tradier access proves unavailable. It reports
contract terms, daily trades and the last national best bid/offer at report
generation. It cannot supply an intraday chain on the free tier. The report's
creation timestamp is not an individual quote-event timestamp. Exact free
history/rate limits need an authenticated check: the subscription documentation
contains inconsistent descriptions of those limits.

Alpaca's free indicative options feed is unsuitable as the sole evidence for
strategy profitability: the provider states that quotes are modified and trades
are delayed derivatives. It can exercise software integration, but must not be
treated as observed executable market quotes.

Implement Tradier only initially. Do not build the alternative adapters or
silently switch feeds. Revisit provider choice if a concrete access or coverage
failure prevents the intended component from working.

## Consequences for evaluation

- Ashwin explicitly required prevention of look-ahead from the 15-minute lag.
  For example, a decision committed at 10:00 cannot buy or sell using a 09:45
  quote received at 10:00. Polling again does not change that quote's market time.
- Preserve market time, receipt time, stated delay, source and missing contract
  terms. Never silently fill missing prices, Greeks or deliverables.
- Preserve bid and ask timestamps separately when supplied. Missing market
  timestamps remain unknown; receipt time cannot substitute for them. Never add
  15 minutes to a quote timestamp to make it appear current. A nominal feed delay
  also does not prove when a particular observation became available.
- Research inputs and simulated execution must respect when information became
  available. News seen now cannot earn a simulated fill against a quote from
  15 minutes earlier. Historical replay needs its own consistent information
  cutoff and timing rules.
- The initial Tradier output is research evidence and is ineligible for the
  current execution path. A future delayed-data simulator must commit decisions
  before eligible market observations, retain when outcomes became knowable and
  prevent subsequent decisions from using undelivered fills or marks. Historical
  replay must exclude later news, revised data and future agent/tool outputs.
  Such a simulator is a separate deliverable; increasing quote-age limits is not
  a substitute for implementing it.
- Delayed or daily observations can support explicitly scoped analyses. They do
  not validate immediate fills, intraday execution quality or every strategy
  family. A quote is not evidence that an order filled.
- Consider paid data when a specific missing history, frequency or field blocks
  a worthwhile hypothesis test. Limited-data profitability alone is insufficient
  evidence to call a strategy established.
- Personal API access does not establish public redistribution rights. Verify
  demo data permissions separately before publication.

## Existing guards and regression coverage

The current equity/ETF ledger already rejects pre-reservation quotes in
`fill_order`, and replay rejects fills with quotes outside reservation/application
time. The operating worker restricts quote freshness to at most 60 seconds.
These are existing safeguards, not a newly discovered 15-minute execution bug.

Regression cases in `tests/test_paper.py` cover a 15-minute-old quote for both
buy and sell orders even with a deliberately relaxed low-level freshness policy,
and a forged fill rejected during replay. `tests/test_paper_operations.py` covers
a newly received batch containing 15-minute-old market quotes. They use explicit
synthetic equity fixtures; they do not qualify authenticated Tradier options
access or establish strategy profitability.

Verification on 2026-10-05: the two paper test modules passed all 62 tests;
Ruff lint/format checks and `git diff --check` passed. Independent read-only
inspection confirmed the existing timing guards and the missing availability
metadata in the equity quote path. No runtime execution behavior was changed.

Adapter and workflow tests now also cover original bid/ask timestamp retention,
missing/asymmetric timestamps, delayed-feed designation, immutable receipt times,
committed retry recovery, cancellation and exclusion from execution. Real-feed
qualification remains pending; the implementation report records current results.

## Primary sources checked 2026-10-05

- [Tradier onboarding](https://docs.tradier.com/docs/getting-started) and
  [API access](https://production.tradier.com/businesses/fintechs).
- [Tradier market data](https://docs.tradier.com/docs/market-data),
  [option chains](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains)
  and [FAQ](https://docs.tradier.com/docs/faq).
- [ThetaData subscriptions](https://thetadata.net/docs/Articles/Getting-Started/Subscriptions.html)
  and [options end-of-day schema](https://thetadata.net/docs/operations/option_history_eod.html).
- [Alpaca option-chain feed semantics](https://docs.alpaca.markets/us/reference/optionchain)
  and [historical options data](https://docs.alpaca.markets/us/docs/historical-option-data).
