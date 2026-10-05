# Verification record

Local verification on October 5, 2026 covered the following boundaries. These
checks establish engineering behavior within the stated scope; they are not
investment-performance results.

| Area | Execution and evidence |
| --- | --- |
| Market experiments | Acquired 81 real TSLA sessions, executed built-in and isolated generated policies, and retained actual calls, data, code and results. The case is explicitly labelled direct tool verification, not autonomous model research. |
| Source connectors | Actual ClinicalTrials.gov, PubMed and market-data requests succeeded with retained provenance. |
| Retrieval | Real BGE model retrieval succeeded, including a repeat query reusing cached vectors inside the deployed API container. |
| Generated tools | A generated arithmetic tool passed independently specified examples and was invoked in real Docker containers. This checks execution and promotion boundaries, not scientific usefulness. |
| Database | PostgreSQL 17.11 integration tests exercised concurrency, leases, cancellation and rollback. SQLite covers local execution. |
| Deployment | An isolated Compose deployment built backend/frontend images, served HTML and static assets, reached PostgreSQL, and passed authentication, read-only mutation rejection and origin checks. Containers ran nonroot; the API had no Docker socket, Docker executable or model credentials. Temporary deployment resources were removed. |
| Research quality | Deterministic tests cover source integrity, quotations, trial/claim links, abstention consistency, extraction scoring and label isolation. All gold fixtures used by these tests are explicitly synthetic. |
| Specialists | Scripted-provider tests exercise reviewed profile creation, delegation, tool restrictions and resume behavior. They are orchestration tests, not real model-quality measurements. |

Run the checks documented in [operations](operations.md) and the repository CI
workflow to reproduce the corresponding engineering tests. Network source checks
depend on the providers' current availability. Integration tests require their
declared disposable services; no test should quietly substitute fake production
research for an unavailable dependency.

The real model-driven research workflow still needs validation with an
authenticated provider. No independently labelled real-world benchmark score,
prospective forecast record, autonomous trading result or remote CI result is
claimed by this verification record.

## Paper operations milestone, 2026-10-05

The staged engineering method and remaining component gates are recorded in
[the roadmap](engineering-roadmap.md); this milestone does not qualify the full
investment system.

- 420 Python tests passed with external integration, sandbox and live-provider
  tests excluded. New cases include strict quote/calendar boundaries, hand-derived
  P&L, mandate controls, reviewed-intent admission, liquidity reuse, close scheduling,
  missing baselines, same-tick drawdown and rollback. Test market inputs are synthetic.
- Four additional tests passed against actual PostgreSQL 17.11 in disposable
  schemas: competing claims, competing control changes, a halt during quote fetch,
  and failure after ledger flush followed by a single successful retry.
- 52 frontend tests, TypeScript and a production build passed. An actual isolated
  API response passed the production frontend parser. Browser review verified the
  empty main state and mandate form, then a separate explicitly synthetic account:
  active → exit only → halted controls, unchanged held positions, stale valuations,
  missing P&L baselines, chart gaps and failure messages. Duplicate rounded chart
  labels were corrected and visually rechecked. Temporary QA services were stopped;
  no synthetic mandates or valuations were added to the main account.
- Independent review identified and reproduced Decimal-spelling liquidity reuse,
  drawdown-latch bypass, missed close windows, incompatible closing freshness and
  truncated baseline issues. Fixes have regression coverage. Drawdown is also
  rechecked after each accepted fill before subsequent entries.
- Ruff lint/format and diff whitespace checks passed. CI now includes the new
  PostgreSQL operations tests; remote CI has not run because publication is pending.

The local app starts with no saved/active mandate, no market credentials and no
paper worker heartbeat. This is an honest unconfigured state. The authenticated
Alpaca smoke is unrun; no brokerage orders, live-feed trading record, or investment
performance result is claimed. Source calendar completeness is an explicit provider
assumption with retained query coverage and change detection.

The optional paper-worker container was also executed against temporary SQLite
inside a network-disabled, read-only-rootfs container. It ran as UID/GID 10001,
without Docker or market/model credentials, recorded `data_blocked` with
`FEED_UNCONFIGURED`, and produced zero ledger events/observations. Read-only mode
exited before creating its test database. The disposable container and temporary
image were removed. Compose configuration validation passed without exposing secrets.
