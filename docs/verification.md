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
