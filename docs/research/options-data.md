# Delayed options research data

Implemented 2026-10-05. Provider: Tradier sandbox, selected by Ashwin under a
free-API budget. This component acquires research evidence. It does not select
strategies, implement options fills or establish profitability.

## Research workflow

1. An investigation has a research question and optional retained hypothesis or
   source records. `discover_options_expirations` saves the provider's returned
   expirations for an underlying. Availability does not establish liquidity.
2. `acquire_options_chain` takes an underlying, one expiration, a purpose and
   optional same-case source IDs. The agent chooses the expiration from its
   question/horizon; the system does not force the nearest date.
3. Fixed read-only HTTPS calls retrieve the sandbox response. The parser validates
   identity against OCC symbol, expiration, underlying, right and strike; it
   preserves missing/zero/crossed/asynchronous quote observations with explicit
   issues. Malformed or conflicting identities fail the acquisition.
4. The immutable `options_chain.v1` artifact binds the purpose and exact source
   hashes. The compact tool receipt includes provenance and a bounded summary;
   `inspect_source` supports exact JSON-pointer navigation through contract rows,
   and `read_artifact` provides complete paginated content.
5. The app inspector displays calls/puts, prices, original source times, data
   conditions, contract details and provenance. A refresh creates a new artifact.

Both tools are available to the four base research roles. Existing specialist
profiles still restrict their explicitly reviewed tool permissions. Options
observations can justify a specialist proposal or support a saved hypothesis.
The [generated architecture map](../generated/agent-architecture.md) lists the
actual tools and descriptions. Broad prompt redesign remains a separate todo.

## Timing and meaning

The feed is declared 900 seconds delayed. Each side retains its raw provider
timestamp and, when unambiguously in the supported millisecond format, normalized
UTC time. Acquisition start and receipt are independent timestamps. Neither
receipt nor a nominal-delay adjustment replaces market time. Missing market time
remains unknown. A response hash identifies the original bytes; normalized
artifacts retain selected validated fields, not a complete raw response archive.

A 10:00 decision cannot fill at a 09:45 quote received at 10:00. Current options
artifacts are execution-ineligible by type and cannot be used as an equity
dataset or execution-eligible experiment. No delayed options simulator exists.
Building one later requires frozen decisions, information-availability cutoffs,
later market observations and explicit execution assumptions. Current equity
freshness/predecision guards must not be loosened to substitute for that work.

Provider-returned rows are not proof of full market or historical coverage. The
chain endpoint documents no pagination; unexpected continuation fields fail.
One request is bounded by time, bytes and contract count. Duplicate identical rows
are counted/deduplicated; conflicting duplicates fail. Credentials remain in
authentication headers, errors are sanitized, and redirects/proxies are disabled.

The source does not establish adjusted deliverables, premium multipliers,
settlement or exercise terms. Those remain unverified; nonstandard sizes or
adjusted roots are flagged unsupported. Quote-size units are explicitly unverified
because the public examples are ambiguous; no multiplication by 100 or contract
liquidity inference is made. Sandbox Greeks are unavailable. Open interest and
volume retain missing values and lack independent field timestamps. Quote-age
diagnostics do not imply an open market, valid fill or current liquidity.

## Configure and verify

Set `RESEARCHDESK_TRADIER_SANDBOX_TOKEN` in the repository's ignored `.env`.
Use a sandbox token from the user's account; no account creation or subscription
is performed. Native CLI commands reread configuration each invocation. Restart
an already running research worker after changing credentials. Compose passes
the token only to the research worker, not the API/frontend/paper worker.

`researchdesk doctor` reports configuration, not successful authentication. With
an existing case, use the commands in the [README](../../README.md). The operator
path uses the same parser/acquisition code with no fabricated agent attribution.
Agent retries recover the committed artifact without fetching changed data.
Cancellation/lease checks fence commits after a network call.

For offline UI verification only:

```sh
python examples/options_data_verification.py \
  --database-url sqlite:///./data/researchdesk.db
```

This creates a new clearly labeled synthetic TEST case using the real parser and
store with a mock HTTP transport. It supplies no market evidence, model results,
trading performance or proof of authenticated access. Repeated runs create new
cases; use an isolated database when a persistent preview is unnecessary.

## Verification status

- Full backend suite: 1,136 passed, 19 skipped. Skips include separately gated
  integration checks; this is not proof that every external service ran.
- Production frontend build and TypeScript passed after the evidence-tab and
  provenance-label fixes. All 103 frontend tests passed across verification runs,
  with a timing caveat: the final two-worker full run had 94 passes and nine
  five-second timeouts. A single-worker rerun of the four affected files passed
  40 of 42; all original failures recovered, but two different options tests hit
  that limit. Those two passed a focused rerun using a 30-second process-local
  timeout (9.95 seconds for the entire run). No assertions failed, no test was
  removed and no source timeout was increased. Host load average was 27.45 with
  substantial memory compression/swapping. This is not a clean final full-suite
  run or a UI performance benchmark; default-timeout stability should be checked
  on an unloaded host or CI.
- Ruff and formatting checks passed. Independent review found and prompted a
  fix for an extreme JSON decimal exponent; its regression passes. No unresolved
  high/medium-severity finding remained in that read-only review.
- Browser verification passed for Evidence counts and opening records, operator
  attribution, call/put and missing-quote filters, contract search and expanded
  provenance. The inspector rendered without horizontal overflow at desktop and
  390-pixel widths; no browser warning/error logs were recorded. The temporary
  viewport override was reset. The visible case uses explicitly synthetic data.
- Authenticated Tradier acquisition and genuine model-driven tool use: unverified.
  Ashwin confirmed that the token is unavailable for now and asked development
  to continue without it. Do not substitute fixture success for this pending
  check. Paid data and redistribution permissions for a public demo remain
  outside this component.

Commands used (from the repository root, then `web` for frontend checks):

```sh
.venv/bin/python -m pytest -q
node node_modules/next/dist/bin/next build
node node_modules/vitest/vitest.mjs run --maxWorkers=2
node node_modules/vitest/vitest.mjs run \
  src/components/case-screen.test.tsx src/components/options-chain.test.tsx \
  src/components/investigation-overview.test.tsx \
  src/components/operations-screen.test.tsx --maxWorkers=1
node node_modules/vitest/vitest.mjs run src/components/options-chain.test.tsx \
  --maxWorkers=1 --testTimeout=30000 \
  -t 'filters recorded rows|paginates the same saved record'
```

Frontend commands used the bundled Node 24 runtime. The nine skipped tests in
the last focused invocation were excluded by its name filter, not disabled tests.

## Sources

- [Tradier market-data feed semantics](https://docs.tradier.com/docs/market-data)
- [Options chain endpoint](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains)
- [Expiration discovery](https://docs.tradier.com/reference/brokerage-api-markets-get-options-expirations)
- [Quote endpoint fields](https://docs.tradier.com/reference/brokerage-api-markets-get-quotes)
- [Tradier API FAQ](https://docs.tradier.com/docs/faq)
