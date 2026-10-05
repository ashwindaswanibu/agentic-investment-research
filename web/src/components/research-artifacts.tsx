"use client";
import type { ReactNode } from "react";
import type { Json, JsonObject } from "@/lib/contracts";
import { isRecord, label, scalar } from "@/lib/format";
import { JsonDetails, Status, StructuredValues } from "./ui";
import {
  ClinicalObservationLedger,
  EvidenceReferences as References,
} from "./clinical-observations";

const records = (value: Json | undefined): JsonObject[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
const texts = (value: Json | undefined): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
const text = (value: Json | undefined, fallback = "Not recorded"): string =>
  typeof value === "string" && value.trim() ? value : fallback;
const number = (value: Json | undefined): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="result-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}
function TextList({ value }: { value: Json | undefined }) {
  const entries = texts(value);
  return entries.length ? (
    <ul className="research-list">
      {entries.map((entry, i) => (
        <li key={i}>{entry}</li>
      ))}
    </ul>
  ) : (
    <p className="muted">No entries recorded.</p>
  );
}
function ScopeNote({ children }: { children: ReactNode }) {
  return <div className="quality-scope">{children}</div>;
}
function Fields({ value, names }: { value: JsonObject; names: string[] }) {
  return (
    <StructuredValues
      value={Object.fromEntries(
        names
          .filter((name) => name in value)
          .map((name) => [name, value[name]]),
      )}
    />
  );
}

export function ClinicalDossierContent({ content }: { content: JsonObject }) {
  const dossier = isRecord(content.dossier) ? content.dossier : null;
  if (!dossier)
    return (
      <>
        <ScopeNote>
          A structured clinical dossier is unavailable in this record.
        </ScopeNote>
        <JsonDetails value={content} open />
      </>
    );
  const validation = isRecord(content.validation) ? content.validation : {};
  const checkName =
    dossier.schema_version === "clinical-dossier.v2"
      ? "Structure and attribution checks"
      : "Attribution checks";
  const coverage = isRecord(validation.coverage) ? validation.coverage : {};
  const forecast = isRecord(dossier.forecast) ? dossier.forecast : {};
  const failures = records(validation.failed_checks ?? validation.issues);
  return (
    <div className="research-artifact">
      <ScopeNote>
        <strong>
          {validation.valid === true
            ? `${checkName} passed`
            : validation.valid === false
              ? `${checkName} need attention`
              : `${checkName} not recorded`}
        </strong>
        <p>
          These checks cover structure, source versions and quotation presence.
          Source-qualified records also retain context and scoped absence
          checks. Clinical truth, inference quality and predictive skill require
          independent assessment.
        </p>
        {Object.keys(coverage).length > 0 && (
          <Fields
            value={coverage}
            names={[
              "trials",
              "claims",
              "contexts",
              "observations",
              "verified_source_references",
              "distinct_sources",
            ]}
          />
        )}
      </ScopeNote>
      {failures.length > 0 && (
        <Section title="Checks to resolve">
          <ul className="research-list check-failures">
            {failures.slice(0, 8).map((failure, i) => (
              <li key={i}>
                <strong>{text(failure.code)}</strong>
                <p>{text(failure.message)}</p>
                <code>{text(failure.path)}</code>
              </li>
            ))}
          </ul>
          {failures.length > 8 && (
            <p className="muted">
              All {failures.length} failed checks are available in the
              validation record below.
            </p>
          )}
        </Section>
      )}
      <Fields
        value={dossier}
        names={["intervention", "indication", "population"]}
      />
      {dossier.schema_version === "clinical-dossier.v2" ? (
        <ClinicalObservationLedger dossier={dossier} />
      ) : (
        <Section title="Trial evidence">
          {records(dossier.trials).map((trial, i) => (
            <div className="trial-record" key={i}>
              <h4>{text(trial.trial_id, "Trial identifier unavailable")}</h4>
              {isRecord(trial.design) && (
                <StructuredValues value={trial.design} />
              )}
              {records(trial.arms).length > 0 && (
                <div className="table-scroll">
                  <table>
                    <caption>Study arms</caption>
                    <thead>
                      <tr>
                        <th>Arm</th>
                        <th>Intervention</th>
                        <th>Role</th>
                        <th>Planned n</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records(trial.arms).map((arm, j) => (
                        <tr key={j}>
                          <td>{text(arm.label ?? arm.arm_id)}</td>
                          <td>{text(arm.intervention)}</td>
                          <td>{text(arm.role)}</td>
                          <td>{number(arm.planned_n) ?? "Not reported"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {records(trial.endpoints).length > 0 && (
                <div className="table-scroll">
                  <table>
                    <caption>Endpoints</caption>
                    <thead>
                      <tr>
                        <th>Outcome</th>
                        <th>Type</th>
                        <th>Timeframe</th>
                        <th>Prespecified</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records(trial.endpoints).map((endpoint, j) => (
                        <tr key={j}>
                          <td>{text(endpoint.name)}</td>
                          <td>{text(endpoint.kind)}</td>
                          <td>{text(endpoint.timeframe)}</td>
                          <td>{text(endpoint.prespecified)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </Section>
      )}
      <Section title="Claims and cited evidence">
        {records(dossier.claims).map((claim, i) => (
          <details className="claim-record" key={i}>
            <summary>
              <span className="small-caps">
                {claim.kind === "fact"
                  ? "Source-reported fact"
                  : claim.kind === "inference"
                    ? "Inference"
                    : "Unclassified claim"}{" "}
                · {text(claim.id)}
              </span>
              <span>{text(claim.statement)}</span>
            </summary>
            {typeof claim.inference_basis === "string" && (
              <p className="prose">
                <strong>Reasoning beyond the source: </strong>
                {claim.inference_basis}
              </p>
            )}
            <References value={claim.source_refs} />
          </details>
        ))}
      </Section>
      <Section title="Contrary evidence">
        <p className="prose">{text(dossier.contrary_evidence_summary)}</p>
        {texts(dossier.contrary_evidence_claim_ids).length > 0 && (
          <p className="text-small muted">
            Cited claims:{" "}
            {texts(dossier.contrary_evidence_claim_ids).join(", ")}
          </p>
        )}
      </Section>
      <Section title="Missing inputs">
        {records(dossier.missing_inputs).length ? (
          <div className="missing-inputs">
            {records(dossier.missing_inputs).map((missing, i) => (
              <div key={i}>
                <strong>{text(missing.field)}</strong>
                <p>{text(missing.reason)}</p>
                <p className="muted">{text(missing.consequence)}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">No missing inputs were declared.</p>
        )}
      </Section>
      <Section title="Uncertainty">
        <TextList value={dossier.uncertainty} />
      </Section>
      <Section title="Falsifiable forecast">
        <div className="forecast-record">
          {dossier.schema_version === "clinical-dossier.v2" &&
          dossier.forecast === null ? (
            <p className="prose">No forecast submitted</p>
          ) : forecast.status === "abstain" ? (
            <>
              <span className="small-caps">Forecast withheld</span>
              <p className="prose">{text(forecast.abstention_reason)}</p>
            </>
          ) : forecast.status === "forecast" ? (
            <>
              <span className="small-caps">Recorded prediction</span>
              <p className="prose">{text(forecast.prediction)}</p>
            </>
          ) : (
            <p className="muted">Forecast status not recorded.</p>
          )}
          <Fields
            value={forecast}
            names={[
              "target",
              "as_of",
              "horizon",
              "outcome_rule",
              "resolution_source",
              "probability",
            ]}
          />
        </div>
      </Section>
      <JsonDetails title="Attribution validation record" value={validation} />
      <JsonDetails title="Complete clinical dossier" value={content} />
    </div>
  );
}

const scoreValue = (value: Json | undefined) => {
  const parsed = number(value);
  return parsed !== null && parsed >= 0 && parsed <= 1
    ? parsed.toFixed(3)
    : "—";
};
function ExtractionErrors({
  name,
  score,
}: {
  name: string;
  score: JsonObject;
}) {
  const errors = records(score.critical_errors);
  return (
    <details className="json-details extraction-errors">
      <summary>
        {name} critical errors ·{" "}
        {Array.isArray(score.critical_errors) ? errors.length : "Not recorded"}
      </summary>
      {errors.length > 0 ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Reference</th>
                <th>Extracted</th>
              </tr>
            </thead>
            <tbody>
              {errors.map((error, i) => (
                <tr key={i}>
                  <td>
                    <code>{text(error.path)}</code>
                    <br />
                    {label(text(error.code, "unclassified"))}
                  </td>
                  <td>{scalar(error.expected)}</td>
                  <td>{scalar(error.actual)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No critical errors recorded.</p>
      )}
    </details>
  );
}
export function EvaluationContent({ content }: { content: JsonObject }) {
  const candidate = isRecord(content.candidate) ? content.candidate : {};
  const baseline = isRecord(content.baseline) ? content.baseline : {};
  const delta = number(content.f1_delta);
  return (
    <div className="research-artifact">
      <ScopeNote>
        <strong>Extraction comparison</strong>
        <p>
          {text(
            content.scope,
            "A comparison with a reference does not establish clinical truth or predictive skill.",
          )}
        </p>
        <p>{text(content.protocol, "Evaluation protocol not recorded.")}</p>
      </ScopeNote>
      <div className="table-scroll">
        <table className="evaluation-comparison">
          <caption>Frozen output comparison</caption>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Candidate</th>
              <th>Baseline</th>
            </tr>
          </thead>
          <tbody>
            {["precision", "recall", "f1"].map((metric) => (
              <tr key={metric}>
                <th>{metric === "f1" ? "F1" : label(metric)}</th>
                <td>
                  {candidate.valid === true
                    ? scoreValue(candidate[metric])
                    : "—"}
                </td>
                <td>
                  {baseline.valid === true ? scoreValue(baseline[metric]) : "—"}
                </td>
              </tr>
            ))}
            {[
              "true_positives",
              "false_positives",
              "false_negatives",
              "reference_fields",
              "candidate_fields",
            ].map((metric) => (
              <tr key={metric}>
                <th>{label(metric)}</th>
                <td>{number(candidate[metric]) ?? "—"}</td>
                <td>{number(baseline[metric]) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {delta !== null &&
        candidate.valid === true &&
        baseline.valid === true && (
          <p className="evaluation-delta">
            F1 difference{" "}
            <strong>
              {delta > 0 ? "+" : ""}
              {delta.toFixed(3)}
            </strong>
          </p>
        )}
      <p className="page-note">
        Scores range from 0 to 1 and measure agreement with the supplied
        reference. A scorable output can still contain critical errors.
      </p>
      <ExtractionErrors name="Candidate" score={candidate} />
      <ExtractionErrors name="Baseline" score={baseline} />
      <Section title="Scoring boundaries">
        <TextList value={candidate.limitations} />
      </Section>
      <JsonDetails
        title="All field errors, scores and frozen input versions"
        value={content}
      />
    </div>
  );
}

export function SpecialistContent({ content }: { content: JsonObject }) {
  return (
    <div className="research-artifact">
      <Fields
        value={content}
        names={["name", "domain", "mandate", "signal_rationale"]}
      />
      <Section title="Evidence standards">
        <p className="prose">{text(content.evidence_standards)}</p>
      </Section>
      <Section title="Output standards">
        <p className="prose">{text(content.output_standards)}</p>
      </Section>
      <Section title="Allowed research tools">
        <div className="tool-tags">
          {texts(content.allowed_tools).map((tool) => (
            <code key={tool}>{tool}</code>
          ))}
        </div>
      </Section>
      <ScopeNote>
        A specialist specification defines a research remit and tool scope.
        Activation requires an independent review of this version; it does not
        establish empirical research quality.
      </ScopeNote>
      <JsonDetails
        title="Instructions, supporting evidence and specification"
        value={content}
      />
    </div>
  );
}

export function ToolQualificationContent({ content }: { content: JsonObject }) {
  const results = Array.isArray(content.results) ? content.results : null;
  const passed = results?.filter(
    (result) => isRecord(result) && result.passed === true,
  ).length;
  const failed = results?.filter(
    (result) => isRecord(result) && result.passed === false,
  ).length;
  const unresolved =
    results === null ? null : results.length - (passed ?? 0) - (failed ?? 0);
  return (
    <div className="research-artifact">
      {typeof content.status === "string" && <Status value={content.status} />}
      <div
        className="experiment-metrics"
        role="group"
        aria-label="Recorded qualification checks"
      >
        <div>
          <span>Passed</span>
          <strong>{passed ?? "—"}</strong>
        </div>
        <div>
          <span>Failed</span>
          <strong className={failed ? "metric-negative" : undefined}>
            {failed ?? "—"}
          </strong>
        </div>
        <div>
          <span>Unresolved</span>
          <strong>{unresolved ?? "—"}</strong>
        </div>
      </div>
      <ScopeNote>
        {text(
          content.limitations,
          "These examples check declared tool behavior. They do not establish scientific truth or investment performance.",
        )}
      </ScopeNote>
      {results?.map((result, i) => (
        <details className="json-details" key={i}>
          <summary>
            Test {i + 1} ·{" "}
            {isRecord(result) && result.passed === true
              ? "Passed"
              : isRecord(result) && result.passed === false
                ? "Failed"
                : "Unresolved"}
          </summary>
          <JsonDetails
            title="Input binding and execution result"
            value={result}
            open
          />
        </details>
      ))}
      <JsonDetails
        title="Qualification record and exact code bindings"
        value={content}
      />
    </div>
  );
}

export function ResearchArtifactContent({
  kind,
  content,
}: {
  kind: string;
  content: Json;
}) {
  if (!isRecord(content))
    return (
      <>
        <ScopeNote>
          Structured details are unavailable for this record.
        </ScopeNote>
        <JsonDetails value={content} open />
      </>
    );
  if (kind === "clinical_dossier")
    return <ClinicalDossierContent content={content} />;
  if (kind === "evaluation_report")
    return <EvaluationContent content={content} />;
  if (kind === "specialist_spec")
    return <SpecialistContent content={content} />;
  if (kind === "research_tool_qualification")
    return <ToolQualificationContent content={content} />;
  if (kind === "hypothesis")
    return (
      <>
        {typeof content.status === "string" && (
          <Status value={content.status} />
        )}
        <Fields
          value={content}
          names={[
            "mechanism",
            "prediction",
            "falsification_rule",
            "evaluation_plan",
            "competing_explanation",
            "disposition_reason",
            "prior_hypothesis_id",
          ]}
        />
        <JsonDetails
          title="Hypothesis lineage and evidence references"
          value={content}
        />
      </>
    );
  if (kind === "specialist_activation")
    return (
      <>
        <ScopeNote>
          Research-only activation of a reviewed specification. This record
          grants no trading authority and does not measure specialist quality.
        </ScopeNote>
        <StructuredValues value={content} />
        <JsonDetails title="Activation and review versions" value={content} />
      </>
    );
  if (kind === "evaluation_reference")
    return (
      <>
        <ScopeNote>
          Operator-provided evaluation labels. This reference is protected from
          agent tools; its accuracy and independence require operator review.
        </ScopeNote>
        <Fields value={content} names={["reference_id", "coverage", "notes"]} />
        <JsonDetails title="Protected reference labels" value={content} />
      </>
    );
  if (kind === "research_tool_spec")
    return (
      <>
        <Fields
          value={content}
          names={["name", "description", "purpose", "limitations"]}
        />
        <Section title="Declared inputs">
          {records(content.input_fields).map((field, i) => (
            <div className="tool-input-field" key={i}>
              <strong>{text(field.name)}</strong>
              <span>
                {text(field.type)} ·{" "}
                {field.required === true
                  ? "Required"
                  : field.required === false
                    ? "Optional"
                    : "Requirement unknown"}
              </span>
              <p>{text(field.description)}</p>
            </div>
          ))}
        </Section>
        <JsonDetails
          title="Tool specification and source-code version"
          value={content}
        />
      </>
    );
  if (kind === "research_tool_tests")
    return (
      <>
        <ScopeNote>
          {Array.isArray(content.cases)
            ? `${content.cases.length} declared test cases`
            : "Test cases not recorded"}
          . Test definitions are distinct from executed qualification results.
        </ScopeNote>
        <JsonDetails
          title="Test inputs, expected outputs and code binding"
          value={content}
          open
        />
      </>
    );
  if (kind === "research_tool_result")
    return (
      <>
        <Fields value={content} names={["tool_name", "limitations"]} />
        {typeof content.ok === "boolean" && (
          <Status value={content.ok ? "completed" : "failed"} />
        )}
        <JsonDetails title="Input" value={content.input ?? null} />
        {content.error != null && (
          <JsonDetails title="Execution error" value={content.error} open />
        )}
        <JsonDetails title="Tool output" value={content.output ?? null} open />
        <JsonDetails title="Complete invocation record" value={content} />
      </>
    );
  return <JsonDetails value={content} open />;
}
