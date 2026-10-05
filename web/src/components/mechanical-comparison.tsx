"use client";

import type { Json, JsonObject } from "@/lib/contracts";
import { isRecord, label } from "@/lib/format";
import { StructuredValues } from "./ui";

const records = (value: Json | undefined): JsonObject[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: Json | undefined): string =>
  typeof value === "string" && value.trim() ? value : "Not recorded";
const count = (value: Json | undefined): number | null =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
const fraction = (value: Json | undefined): number | null =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  value >= 0 &&
  value <= 1
    ? value
    : null;

function delivery(score: JsonObject) {
  const matched = count(score.matched_fields);
  const expected = count(score.expected_fields);
  const delivered = fraction(score.delivered_scoped_fraction);
  const consistent =
    typeof score.status === "string" &&
    ["scored", "no_submission", "invalid_output"].includes(score.status) &&
    matched !== null &&
    expected !== null &&
    expected > 0 &&
    matched <= expected &&
    (score.status === "scored" || matched === 0);
  return {
    counts: consistent ? `${matched} / ${expected}` : "—",
    fraction:
      consistent &&
      delivered !== null &&
      Math.abs(delivered - matched / expected) < 1e-9
        ? delivered
        : null,
    expected,
  };
}

function outputStatus(value: Json | undefined) {
  switch (value) {
    case "scored":
      return "Scored";
    case "no_submission":
      return "No submission";
    case "invalid_output":
      return "Invalid output";
    default:
      return "Not recorded";
  }
}

function schemaStatus(score: JsonObject) {
  const validation = isRecord(score.candidate_validation)
    ? score.candidate_validation
    : {};
  if (validation.schema_valid === true) return "Valid schema";
  if (validation.schema_valid === false) {
    const issues = count(validation.issue_count);
    return `Invalid schema${issues !== null ? ` · ${issues} ${issues === 1 ? "issue" : "issues"}` : ""}`;
  }
  return score.status === "no_submission"
    ? "Not assessed · no submission"
    : "Not recorded";
}

function FieldResults({ name, score }: { name: string; score: JsonObject }) {
  const results = records(score.field_results);
  return (
    <details className="json-details extraction-errors">
      <summary>
        {name} field results · {results.length || "Not recorded"}
      </summary>
      {results.length ? (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label={`${name} field results`}
        >
          <table>
            <caption>{name} guided extraction fields</caption>
            <thead>
              <tr>
                <th scope="col">Requested field</th>
                <th scope="col">Result and reason</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result, index) => (
                <tr key={index}>
                  <td
                    style={{
                      width: "45%",
                      maxWidth: 260,
                      overflowWrap: "anywhere",
                    }}
                  >
                    <strong>{label(text(result.field_name))}</strong>
                    <br />
                    <code>{text(result.field_id)}</code>
                    <br />
                    <span className="muted">
                      Observation: {text(result.observation_id)}
                    </span>
                  </td>
                  <td style={{ maxWidth: 300, overflowWrap: "anywhere" }}>
                    <strong>{label(text(result.status))}</strong>
                    <br />
                    {label(text(result.reason))}
                    <p className="muted">
                      Value agreement:{" "}
                      {result.value_agreement === true
                        ? "Yes"
                        : result.value_agreement === false
                          ? "No"
                          : "Not assessed"}
                    </p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No field results recorded.</p>
      )}
    </details>
  );
}

function SafeReceipt({
  receipt,
  names,
}: {
  receipt: JsonObject;
  names: string[];
}) {
  const selected = Object.fromEntries(
    names
      .filter((name) => typeof receipt[name] === "string")
      .map((name) => [name, receipt[name]]),
  );
  return Object.keys(selected).length ? (
    <StructuredValues value={selected} />
  ) : (
    <p className="muted">Receipt not recorded.</p>
  );
}

export function MechanicalComparisonContent({
  content,
}: {
  content: JsonObject;
}) {
  const candidate = isRecord(content.candidate) ? content.candidate : {};
  const baseline = isRecord(content.baseline) ? content.baseline : {};
  const candidateDelivery = delivery(candidate);
  const baselineDelivery = delivery(baseline);
  const delta = content.delivered_scoped_fraction_delta;
  const showDelta =
    typeof delta === "number" &&
    Number.isFinite(delta) &&
    candidateDelivery.fraction !== null &&
    baselineDelivery.fraction !== null &&
    candidateDelivery.expected === baselineDelivery.expected &&
    Math.abs(delta - (candidateDelivery.fraction - baselineDelivery.fraction)) <
      1e-9;
  const sources = records(content.sources);
  const inputs = records(content.inputs);
  return (
    <div className="research-artifact">
      <div className="quality-scope">
        <strong>Guided extraction comparison</strong>
        <p>
          One paired diagnostic over predeclared source fields. A field matches
          only when its value or exact key absence and required source bindings
          match. This does not measure clinical quality, research superiority or
          generalization.
        </p>
      </div>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Guided extraction summary"
      >
        <table className="evaluation-comparison">
          <caption>Delivered fields within the declared scope</caption>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col">Candidate</th>
              <th scope="col">Baseline</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Submission status</th>
              <td>{outputStatus(candidate.status)}</td>
              <td>{outputStatus(baseline.status)}</td>
            </tr>
            <tr>
              <th scope="row">Matched / expected fields</th>
              <td>{candidateDelivery.counts}</td>
              <td>{baselineDelivery.counts}</td>
            </tr>
            <tr>
              <th scope="row">Delivered scoped fraction</th>
              <td>
                {candidateDelivery.fraction !== null
                  ? `${(candidateDelivery.fraction * 100).toFixed(1)}%`
                  : "—"}
              </td>
              <td>
                {baselineDelivery.fraction !== null
                  ? `${(baselineDelivery.fraction * 100).toFixed(1)}%`
                  : "—"}
              </td>
            </tr>
            <tr>
              <th scope="row">Complete dossier schema</th>
              <td>{schemaStatus(candidate)}</td>
              <td>{schemaStatus(baseline)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="evaluation-delta">
        Candidate − baseline delivered fraction
        <strong>
          {showDelta
            ? `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)} pp`
            : "Not available"}
        </strong>
      </p>
      <p className="page-note">
        The denominator includes every declared field, including missing
        submissions and invalid records. Schema validation is separate from
        scoped field matching: neither establishes clinical correctness. Value
        agreement alone does not establish a match.
      </p>
      <FieldResults name="Candidate" score={candidate} />
      <FieldResults name="Baseline" score={baseline} />
      <details className="json-details">
        <summary>Frozen source bindings and input digests</summary>
        <section className="result-section">
          <h3>Comparison identities</h3>
          <SafeReceipt
            receipt={content}
            names={[
              "dataset_case_id",
              "database_case_id",
              "scope_sha256",
              "reference_sha256",
            ]}
          />
          <h3>Sources</h3>
          {sources.length ? (
            sources.map((receipt, index) => (
              <SafeReceipt
                key={index}
                receipt={receipt}
                names={["source_id", "id", "kind", "sha256"]}
              />
            ))
          ) : (
            <p className="muted">No source bindings recorded.</p>
          )}
          <h3>Frozen inputs</h3>
          {inputs.length ? (
            inputs.map((receipt, index) => (
              <SafeReceipt
                key={index}
                receipt={receipt}
                names={["id", "kind", "sha256"]}
              />
            ))
          ) : (
            <p className="muted">No input digests recorded.</p>
          )}
        </section>
      </details>
    </div>
  );
}
