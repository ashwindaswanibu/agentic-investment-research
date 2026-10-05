"use client";

import type { ReactNode } from "react";
import type { Json, JsonObject } from "@/lib/contracts";
import { isRecord, label } from "@/lib/format";

const records = (value: Json | undefined): JsonObject[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: Json | undefined, fallback = "Not recorded") =>
  typeof value === "string" && value.trim() ? value : fallback;
const ids = (value: Json | undefined) =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

function pointer(value: Json | undefined) {
  return value === "" ? "(document root)" : text(value);
}

export function EvidenceReferences({ value }: { value: Json | undefined }) {
  return (
    <div className="claim-sources">
      {records(value).map((source, i) => (
        <div className="claim-source" key={i}>
          {typeof source.excerpt === "string" && (
            <blockquote>{source.excerpt}</blockquote>
          )}
          <dl>
            <div>
              <dt>Source artifact</dt>
              <dd className="mono break-all">{text(source.artifact_id)}</dd>
            </div>
            <div>
              <dt>Exact version</dt>
              <dd className="mono break-all">
                {text(source.artifact_sha256 ?? source.sha256)}
              </dd>
            </div>
          </dl>
          {typeof source.source_path === "string" && (
            <code className="break-all">{pointer(source.source_path)}</code>
          )}
        </div>
      ))}
    </div>
  );
}

function Anchor({ value }: { value: Json | undefined }) {
  if (!isRecord(value))
    return <p className="muted">Exact source location not recorded.</p>;
  return (
    <div className="text-small">
      <p className="mono break-all">{text(value.artifact_id)}</p>
      <code className="break-all">{pointer(value.source_path)}</code>
      <details className="claim-record">
        <summary>Exact source version</summary>
        <EvidenceReferences
          value={[
            {
              artifact_id: value.artifact_id ?? null,
              artifact_sha256: value.artifact_sha256 ?? null,
            },
          ]}
        />
      </details>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="result-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function presentText(value: Json | undefined, humanize = false): string {
  if (value === null) return "Present · null";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") return humanize ? label(value) : value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string"))
    return value.map((item) => (humanize ? label(item) : item)).join(" + ");
  return "Present value has an unsupported shape";
}

function FieldState({
  value,
  humanize = false,
}: {
  value: Json | undefined;
  humanize?: boolean;
}) {
  if (!isRecord(value))
    return <span className="muted">Field not recorded</span>;
  if (value.state === "present") {
    if (!("value" in value))
      return <span className="muted">Present value not recorded</span>;
    return <span>{presentText(value.value, humanize)}</span>;
  }
  if (value.state === "unresolved" || value.state === "not_applicable")
    return (
      <>
        <strong>
          {value.state === "unresolved" ? "Unresolved" : "Not applicable"}
        </strong>
        <p>{text(value.reason, "Reason not recorded.")}</p>
      </>
    );
  if (value.state === "source_absent") {
    const proof = isRecord(value.proof) ? value.proof : {};
    return (
      <>
        <strong>Source key absent</strong>
        <p>{text(value.reason, "Reason not recorded.")}</p>
        <p className="text-small">
          Exact missing key:{" "}
          <code className="break-all">
            {typeof proof.key === "string"
              ? JSON.stringify(proof.key)
              : "Not recorded"}
          </code>
        </p>
        <Anchor value={proof.parent} />
        <p className="text-small muted">
          This assertion concerns this key only, not all available evidence.
        </p>
      </>
    );
  }
  return <span className="muted">Unrecognized field state</span>;
}

type FieldSpec = { name: string; title?: string; humanize?: boolean };
const fields: Record<string, FieldSpec[]> = {
  design: [
    { name: "study_type", title: "Study type", humanize: true },
    { name: "allocation", humanize: true },
    { name: "intervention_model", title: "Intervention model" },
    { name: "masking" },
    { name: "phase" },
    { name: "comparator_source", title: "Comparator source", humanize: true },
  ],
  population_count: [
    { name: "count" },
    { name: "unit" },
    { name: "population_definition", title: "Population definition" },
    { name: "reported_stage", title: "Source-reported stage" },
    {
      name: "stages",
      title: "Population conditions (all apply)",
      humanize: true,
    },
    { name: "assignment_basis", title: "Assignment basis", humanize: true },
    {
      name: "reported_status",
      title: "Source-reported status",
      humanize: true,
    },
  ],
  endpoint: [
    { name: "definition" },
    { name: "reported_role", title: "Source-reported role", humanize: true },
    { name: "timeframe" },
    { name: "time_origin", title: "Time measured from" },
    { name: "population_definition", title: "Population definition" },
    { name: "comparator_description", title: "Comparison" },
    { name: "prespecification", title: "Prespecification", humanize: true },
  ],
  availability: [{ name: "available", title: "Available in the stated scope" }],
};

function Group({ value }: { value: JsonObject }) {
  return (
    <div className="claim-source">
      <p className="text-small">
        <strong>Source group: </strong>
        <code>
          {typeof value.local_id === "string"
            ? JSON.stringify(value.local_id)
            : "Not recorded"}
        </code>
      </p>
      <Anchor value={value.container} />
    </div>
  );
}

function Observation({
  value,
  contexts,
}: {
  value: JsonObject;
  contexts: JsonObject[];
}) {
  const kind = typeof value.kind === "string" ? value.kind : "unknown";
  const context = contexts.find((item) => item.context_id === value.context_id);
  const count = isRecord(value.count) ? value.count : {};
  const title =
    kind === "population_count"
      ? `Population count${count.state === "present" && "value" in count ? ` · ${presentText(count.value)}` : ""}`
      : kind === "design"
        ? `Design · ${value.design_scope === "trial_assignment" ? "Trial assignment" : value.design_scope === "analysis_comparison" ? "Analysis comparison" : "Scope not recorded"}`
        : kind === "availability"
          ? `Availability · ${label(text(value.subject, "Unspecified scope"))}`
          : kind === "endpoint"
            ? "Endpoint"
            : "Unrecognized observation";
  const specificCountRef = isRecord(value.count_source_ref)
    ? value.count_source_ref
    : null;
  const specificAvailabilityRef = isRecord(value.available_source_ref)
    ? value.available_source_ref
    : null;
  const refs = records(value.source_refs);
  const prespecificationRefs = records(value.prespecification_refs);
  const normalization: Record<string, string> = {
    none:
      count.state === "present"
        ? "None · direct source value"
        : "None · no count value submitted",
    integer_from_digit_string: "Digit string converted to an integer",
    reported_in_text: "Count extracted from source text",
  };
  return (
    <section
      className="trial-record"
      aria-label={`Observation ${text(value.observation_id)}`}
    >
      <h4>{title}</h4>
      <p className="text-small mono break-all">{text(value.observation_id)}</p>
      <p className="text-small muted">
        Context:{" "}
        {context ? text(context.label) : text(value.context_id, "Not recorded")}
        {context && <> · {text(context.trial_id)}</>}
      </p>
      {!fields[kind] ? (
        <p className="muted">
          This observation kind is not supported by this view.
        </p>
      ) : (
        <dl className="structured-values">
          {fields[kind].map((field) => (
            <div key={field.name}>
              <dt>{field.title || label(field.name)}</dt>
              <dd>
                <FieldState
                  value={value[field.name]}
                  humanize={field.humanize}
                />
              </dd>
            </div>
          ))}
          {kind === "population_count" && (
            <div>
              <dt>Count normalization</dt>
              <dd>
                {typeof value.count_normalization === "string"
                  ? normalization[value.count_normalization] ||
                    "Unrecognized normalization"
                  : "Not recorded"}
              </dd>
            </div>
          )}
        </dl>
      )}
      {kind === "population_count" && value.group === null && (
        <p className="text-small muted">
          No local group specified for this population.
        </p>
      )}
      {isRecord(value.group) && <Group value={value.group} />}
      {records(value.groups).map((group, i) => (
        <Group value={group} key={i} />
      ))}
      {typeof value.endpoint_observation_id === "string" && (
        <p className="text-small break-all">
          Endpoint observation: {value.endpoint_observation_id}
        </p>
      )}
      {ids(value.population_count_ids).length > 0 && (
        <p className="text-small break-all">
          Population counts: {ids(value.population_count_ids).join(", ")}
        </p>
      )}
      {kind === "availability" && (
        <p className="prose">{text(value.scope_description)}</p>
      )}
      {(refs.length > 0 ||
        specificCountRef ||
        specificAvailabilityRef ||
        prespecificationRefs.length > 0) && (
        <details className="claim-record">
          <summary>Citations for {text(value.observation_id)}</summary>
          {specificCountRef && (
            <>
              <h5>Count source</h5>
              <EvidenceReferences value={[specificCountRef]} />
            </>
          )}
          {specificAvailabilityRef && (
            <>
              <h5>Availability source</h5>
              <EvidenceReferences value={[specificAvailabilityRef]} />
            </>
          )}
          {prespecificationRefs.length > 0 && (
            <>
              <h5>Prespecification evidence</h5>
              <EvidenceReferences value={prespecificationRefs} />
            </>
          )}
          {refs.length > 0 && (
            <>
              <h5>Observation evidence</h5>
              <EvidenceReferences value={refs} />
            </>
          )}
        </details>
      )}
    </section>
  );
}

export function ClinicalObservationLedger({
  dossier,
}: {
  dossier: JsonObject;
}) {
  const contexts = records(dossier.contexts);
  const observations = records(dossier.observations);
  const reconciliations = records(dossier.reconciliations);
  return (
    <>
      <Section title="Source and analysis contexts">
        <p className="prose muted">
          Each observation retains its source context. Counts, groups and
          analyses are not merged across records.
        </p>
        {records(dossier.trials).map((trial, i) => (
          <p className="text-small" key={i}>
            <strong>{text(trial.trial_id)}</strong> · Study family:{" "}
            {text(trial.trial_family_id)}
          </p>
        ))}
        {contexts.length ? (
          contexts.map((context, i) => (
            <details className="claim-record" key={i}>
              <summary>
                <span className="small-caps">
                  {label(text(context.kind, "Unspecified context"))} ·{" "}
                  {text(context.trial_id)}
                </span>
                <span>{text(context.label)}</span>
                <span className="mono break-all">
                  {text(context.context_id)}
                </span>
              </summary>
              {typeof context.analysis_id === "string" && (
                <p className="text-small break-all">
                  Analysis identity: {context.analysis_id}
                </p>
              )}
              <Anchor value={context.source} />
            </details>
          ))
        ) : (
          <p className="muted">No source contexts recorded.</p>
        )}
      </Section>
      <Section title="Source-qualified observations">
        {observations.length ? (
          observations.map((observation, i) => (
            <Observation value={observation} contexts={contexts} key={i} />
          ))
        ) : (
          <p className="muted">No observations recorded.</p>
        )}
      </Section>
      <Section title="Reconciliation across observations">
        {reconciliations.length ? (
          reconciliations.map((item, i) => (
            <section
              className="trial-record"
              aria-label={`Reconciliation ${i + 1}`}
              key={i}
            >
              <h4>
                {item.kind === "fact"
                  ? "Source-reported reconciliation"
                  : item.kind === "inference"
                    ? "Inferred reconciliation"
                    : "Unclassified reconciliation"}
              </h4>
              <p className="small-caps">{label(text(item.relationship))}</p>
              <p className="prose">{text(item.explanation)}</p>
              <p className="text-small break-all">
                Observations:{" "}
                {ids(item.observation_ids).join(", ") || "Not recorded"}
              </p>
              {typeof item.inference_basis === "string" && (
                <p className="prose">
                  <strong>Reasoning beyond the source: </strong>
                  {item.inference_basis}
                </p>
              )}
              {records(item.source_refs).length > 0 && (
                <details className="claim-record">
                  <summary>Reconciliation citations</summary>
                  <EvidenceReferences value={item.source_refs} />
                </details>
              )}
            </section>
          ))
        ) : (
          <p className="muted">
            No reconciliation was submitted; observations remain separate.
          </p>
        )}
      </Section>
    </>
  );
}
