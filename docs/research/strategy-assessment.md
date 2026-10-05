# Automatic strategy assessment

2026-10-05. This component answers what a recorded experiment demonstrates. It
does not approve a strategy, grade originality, or turn historical returns into
an alpha claim. It is part of the application workflow, not an operator's manual
review process.

## Decision and scope

The visible strategy was an operator-authored implementation example: a 20-session
moving-average filter with volatility-scaled exposure. Executing Python in a
sandbox is meaningful engineering evidence; it does not demonstrate a novel
investment mechanism. The two retained experiments contain one stock over one
historical interval, fixed costs and no train/test folds or prospective outcomes.

Use deterministic evidence accounting first. The report reconciles returns,
account observations, drawdown, fill count and fees; compares recorded cash and
buy-and-hold baselines; measures closing exposure; and records absent validation.
Its gaps describe what is supplied to this assessment, not a claim to have
searched every external record. The method is versioned `strategy-assessment.v1`.

We considered a language-model grading prompt and a statistical significance
score. A model's judgment would not independently verify these numbers. The
complete candidate-search history needed for selection-aware significance is
absent. No significance score is manufactured from one short selected run.
The [backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
explains why selecting among repeated historical tests can produce misleading
results; its PBO method is not implemented here. QuantConnect's
[research guide](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/research-guide)
also tracks repeated tests as an overfitting concern. These inform the required
evidence; they do not establish the quality of this platform's strategies.

## Implemented path

`ResearchTools.experiment` runs its existing computation, then `assessed_result`
attaches the deterministic report before the artifact is committed. The result
digest covers both the simulation and assessment. There is no second transaction
whose failure could leave a new successful experiment without its assessment.
The compact agent tool response includes the report, and the runtime prompt tells
agents to inspect its baselines, exposure and gaps. Existing paper authorization
rules are unchanged; an assessment is not an authorization.
The prompt also directs agents to use the existing hypothesis-disposition tool
to record evidence-backed rejection or inconclusive outcomes. This is guidance
over an implemented recording tool, not a validated autonomous quality judge or
a new continuous strategy-retirement scheduler.

Older immutable experiments receive a separate annotation through:

```sh
python -m researchdesk.cli assess-strategy --experiment-id EXISTING_EXPERIMENT_ID
```

The annotation binds the original ID and hash, has its own method version and
idempotency key, and cannot authorize execution. Repeating the command returns
the same annotation. Read-only configuration rejects writes. There are no model
or network calls in the assessor.

Historical simulations and reset walk-forward folds remain distinct. Each fold's
accounting and chronology are checked; overlap or training extending into the test
period fails assessment. The linked return is explicitly not a continuous account
return, and no combined drawdown or Sharpe is fabricated. Closing exposure is an
arithmetic mean of daily invested fractions, not a matched-risk alpha estimate.

## Existing TSLA results

Both experiments span 2025-01-02 through 2025-04-30, 81 observed sessions, with
$10,000 initial capital and assumed fees/slippage of 1/5 basis points.

| Recorded policy | Net return | Max drawdown | Mean closing allocation | Fills |
|---|---:|---:|---:|---:|
| SMA, 20 sessions | −15.78% | 22.32% | 15.45% | 6 |
| Volatility-scaled SMA | −2.59% | 3.87% | 2.52% | 6 |
| Recorded buy-and-hold baseline | −22.90% | 42.88% | Not reconstructed by this report | 1 |
| Recorded cash baseline (zero yield) | 0% | Not supplied | 0% | — |

Both policies lost money and trailed the recorded cash baseline. The volatility
policy was invested at 14 session closes and reached a maximum closing allocation
of 16.92%. Its +20.31 percentage-point difference against buy-and-hold cannot be
interpreted as alpha: the exposures differ and no selection-adjusted or
prospective evaluation is supplied. These are illustrative engineering runs,
not model-discovered professional strategies.

Bound original experiment IDs:

- `1df4e68b-044a-4238-a934-842f3a0e012c`: SMA backtest.
- `ff43f877-aaca-4524-83af-5c5bad3d2c39`: executable volatility policy.
- `0bebb10a-1e33-478e-aed9-04729bef2415`: generated-policy assessment annotation.

## Verification

The backend suite passed 1,008 tests with 19 integration tests skipped. Nineteen
focused assessment/architecture checks then passed, including the new
architecture drift test. Fixtures cover positive results without alpha approval,
losses that outperform a declining benchmark, cash comparisons, allocation,
malformed/nonfinite metrics, mismatched accounting, missing baselines, leaking or
overlapping folds, immutable annotation and idempotent replay. A domain test
checks that executed generated policies persist the report automatically.

The frontend suite passed 89 tests with two workers. An initial unconstrained run
concurrent with backend tests hit timing limits; limiting workers resolved the
resource contention without changing assertions or extending test timeouts.
The real retained TSLA results were assessed through the shipped CLI; repeating
the generated-policy assessment returned the same annotation ID.

The production build and TypeScript checks passed. Browser verification covered
the actual saved assessment at 1280px desktop and 390px mobile widths, including
the expandable evidence gaps. The comparison table scrolls within its region on
mobile; the page does not overflow horizontally. No browser console errors were
observed. A stale automation tab retained its old mobile size after the viewport
reset; a fresh default-sized tab verified desktop rendering and was left open.

Independent review remains pending because review agents hit account usage
limits. This is local qualification of a bounded diagnostic, not continuous
operation or profitability qualification.

## Next component and boundaries

Options are essential to the intended product. Complete options-chain ingestion
and contract validation next: real strikes, expiries, bid/ask quotes, timestamps,
source/feed identity and explicit missing/stale data. This is the dependency for
researching viable structures. Options selection, Greeks/pricing qualification,
exercise/assignment, settlement and continuous reassessment remain separate
unfinished gates. No options execution or live trading is enabled here.

The [generated architecture map](../generated/agent-architecture.md) shows all
registered tools, agents, prompt assembly and the assessment path. Its regression
check prevents silent drift when registry or prompt code changes.
