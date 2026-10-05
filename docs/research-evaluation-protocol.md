# M1: clinical research evaluation protocol

Status: quality-comparison design specification, 2026-10-05. No real-world score has been measured.
Dataset manifest, adjudicated references, model versions, sample-size rationale,
run budgets and decision thresholds must be frozen before a final comparison.
This specification follows the [engineering roadmap](engineering-roadmap.md).
The [development pilot runner](benchmark-runner.md), frozen manifests and isolated
attempt journal are implemented. The [three-case real corpus](research-benchmark-data.md)
is acquired and import-verified but unlabelled. [ADR 0003](decisions/0003-clinical-reference-scope.md)
records why source-qualified reference work is required before scoring it.

## Question and useful target

Can the system turn dispersed trial registrations and publications into an
accurate, attributable decision dossier, recognize when comparisons are invalid,
and abstain when evidence is insufficient? The useful target is a reviewable
research product whose critical claims survive independent source checking.
This evaluation does not measure clinical efficacy or trading alpha.

## Comparisons

Compare the same available evidence, model version and declared resource budget:

1. A single general research agent using the same retrieval and deterministic tools.
2. A fixed set of specialists with the same case/task budget.
3. The adaptive system that creates a specialist or reusable tool when a retained
   observation establishes a capability gap.

Separate the cost of initial tool/profile development from reuse, and also report
amortized total cost over the evaluated workload. Count failed creations, review
calls and retries. A less expensive architecture that meets the quality target
is a valid result. Do not discard unsuccessful adaptive attempts.

## Cases and references

A case concerns a concrete trial or related study family, with a declared question,
information cutoff and included source manifest. Include registries, protocols,
publications and amendments where available. Cases must include missing results,
contradictory reported values, changed endpoints, subgroup claims, heterogeneous
comparators and apparently plausible but invalid cross-trial comparisons.

Split development and final cases by issuer and trial family, not random document
chunks. Freeze exact source bytes/hashes and acquisition/availability times. Source
availability does not prove an LLM had no prior knowledge; historical dossiers
remain factual-research evaluations, not prospective forecasting demonstrations.

Prepare reference fields and claim-level judgments independently of candidate
outputs. Adjudicate disagreements with retained source passages and rationale.
Use appropriate domain expertise for conclusions that cannot be settled by direct
source extraction. If that expertise is unavailable, mark the evaluation scope
as extraction-only; model agreement does not replace it.

## Outcomes and error taxonomy

Deterministic outcomes: trial/arm/endpoint extraction precision/recall/F1;
identity/date/unit consistency; source-version integrity; unsupported source IDs;
missing required fields; successful execution of declared calculations.

Critical errors include wrong treatment/comparator assignment, wrong denominator,
endpoint/timeframe substitution, unsupported causal or efficacy claims, presenting
an exploratory subgroup as confirmatory, omitting a material conflicting source,
and converting absent evidence into a confident positive conclusion.

Claim review separately scores citation support, factual accuracy, completeness,
comparability, uncertainty and justified abstention. Exact quotation presence is
only an integrity check. Calibrate any model grader against independently judged
examples and report disagreement. Evaluate persisted output and actual execution
state, including blocked work, rather than an agent's assertion of success.

Operational measures: completion/abstention/failure rate, tool selection errors,
retries, elapsed time, token/tool cost and trace completeness. Record provider,
prompt, profile, code, tool, dataset and evaluator versions for every trial.

## Statistical and promotion procedure

Run repeated trials because agent outputs vary. Use paired comparisons at the
case level and account for correlated cases within issuer/study families. Use a
pilot only to estimate variability and decide a useful effect size, sample size,
uncertainty method, noninferiority margins and resource envelope. Freeze those
choices before the final comparison. Report intervals and all outcomes; a small
pilot cannot establish superiority.

Promote a component only within the supported scope after its correctness and
operational gates pass and its quality/cost evidence meets the frozen decision
rule. Any observed critical error must be investigated; a clean finite sample is
not proof of a zero underlying error rate. Retain the simpler comparator if
adaptation adds cost without demonstrated benefit. After tuning on released final
errors, obtain new independent final cases before making a renewed claim.

## Next executable steps

- Implement the source-qualified reference contract and explicit scored-field scope.
- Have references checked independently; record unresolved domain judgments.
- Run the real provider on a pilot after local authentication is available.
- Freeze the final protocol and execute the paired comparison with retained traces.

This procedure is informed by [Anthropic's evaluation methodology](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
and [multi-agent research implementation](https://www.anthropic.com/engineering/multi-agent-research-system),
read on 2026-10-05. Their reported results are not claims about this project.
