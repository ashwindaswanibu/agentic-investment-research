"use client";

import type { ReactNode } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Braces,
  CircleDot,
  FileText,
  GitBranch,
} from "lucide-react";
import type { Artifact, CaseDetail, Json, JsonObject } from "@/lib/contracts";
import { dateTime, isRecord, label } from "@/lib/format";
import { Status } from "./ui";

const text = (value: Json | undefined) =>
  typeof value === "string" ? value.trim() : "";
const records = (value: Json | undefined): JsonObject[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
const content = (artifact?: Artifact): JsonObject =>
  artifact && isRecord(artifact.content) ? artifact.content : {};
const newest = (artifacts: Artifact[]) =>
  [...artifacts].sort(
    (a, b) =>
      (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) ||
      b.id.localeCompare(a.id),
  );

export function investigationReading(data: CaseDetail) {
  const artifacts = newest(data.artifacts);
  const dossierArtifact = artifacts.find((a) => a.kind === "clinical_dossier");
  const hypothesis = artifacts.find((a) => a.kind === "hypothesis");
  const dossierContent = content(dossierArtifact);
  const dossier = isRecord(dossierContent.dossier)
    ? dossierContent.dossier
    : {};
  const claims = records(dossier.claims).filter((claim) =>
    text(claim.statement),
  );
  const missing = records(dossier.missing_inputs).filter(
    (item) => text(item.field) || text(item.reason),
  );
  const uncertainty = Array.isArray(dossier.uncertainty)
    ? (dossier.uncertainty.filter(
        (item) => typeof item === "string" && item.trim(),
      ) as string[])
    : [];
  const sourceIds = new Set<string>();
  for (const claim of claims.slice(0, 3)) {
    for (const ref of records(claim.source_refs)) {
      if (typeof ref.artifact_id === "string") sourceIds.add(ref.artifact_id);
    }
  }
  const evidence = artifacts.filter((a) =>
    ["evidence", "dataset"].includes(a.kind),
  );
  return {
    dossierArtifact,
    dossier,
    claims,
    missing,
    uncertainty,
    hypothesis,
    hypothesisContent: content(hypothesis),
    evidence: [
      ...evidence.filter((a) => sourceIds.has(a.id)),
      ...evidence.filter((a) => !sourceIds.has(a.id)),
    ],
    sharedSourceIds: [...sourceIds].filter(
      (id) => !evidence.some((a) => a.id === id),
    ),
    analyses: artifacts.filter((a) =>
      [
        "experiment",
        "strategy_assessment",
        "research_tool_result",
        "code",
        "review",
        "paper_intent",
      ].includes(a.kind),
    ),
    sourceCheck:
      isRecord(dossierContent.validation) &&
      typeof dossierContent.validation.valid === "boolean"
        ? dossierContent.validation.valid
        : null,
  };
}

function RecordLink({
  artifact,
  onOpen,
  caption,
}: {
  artifact: Artifact;
  onOpen: (a: Artifact) => void;
  caption?: string;
}) {
  return (
    <button
      className="investigation-record-link"
      onClick={() => onOpen(artifact)}
    >
      <span className="investigation-record-icon">
        {artifact.kind === "code" ? (
          <Braces size={17} />
        ) : (
          <FileText size={17} />
        )}
      </span>
      <span>
        <small>{caption || label(artifact.kind)}</small>
        <strong>{artifact.title}</strong>
      </span>
      <ArrowUpRight size={17} />
    </button>
  );
}

export function InvestigationOverview({
  data,
  onOpen,
  onOpenSource,
  loadingSource,
  onNavigate,
  children,
}: {
  data: CaseDetail;
  onOpen: (a: Artifact) => void;
  onOpenSource: (id: string) => void;
  loadingSource: string | null;
  onNavigate: (tab: string) => void;
  children: ReactNode;
}) {
  const reading = investigationReading(data);
  const hypothesis = reading.hypothesisContent;
  const active = data.tasks.filter((t) =>
    ["running", "queued", "waiting"].includes(t.status),
  );
  const failed = data.tasks.filter((t) =>
    ["failed", "blocked"].includes(t.status),
  );
  const hasQuestions =
    reading.missing.length > 0 || reading.uncertainty.length > 0;
  const summary = data.summary?.trim();
  return (
    <div className="investigation-overview">
      <div className="investigation-main">
        <section
          className="investigation-reading"
          aria-labelledby="reading-heading"
        >
          <div className="investigation-section-top">
            <span className="investigation-kicker">
              01 / THE CURRENT READING
            </span>
            <span className="investigation-record-state">
              <CircleDot size={13} /> Recorded research
            </span>
          </div>
          <h2 id="reading-heading">Where the evidence stands.</h2>
          {summary ? (
            <>
              <p className="investigation-summary preserve-lines">{summary}</p>
              <span className="investigation-caption">
                Saved run summary · inspect the supporting records below.
              </span>
            </>
          ) : reading.claims.length ? (
            <p className="investigation-summary">
              {text(reading.claims[0].statement)}
            </p>
          ) : (
            <>
              <p className="investigation-summary">
                {reading.dossierArtifact
                  ? "Evidence is recorded. A research conclusion is still open."
                  : "A question worth investigating."}
              </p>
              <p className="investigation-intro">
                {reading.dossierArtifact
                  ? "The latest dossier contains source observations, without a stated clinical conclusion."
                  : data.hypothesis}
              </p>
            </>
          )}
          {reading.dossierArtifact && (
            <div className="investigation-reading-footer">
              <button onClick={() => onOpen(reading.dossierArtifact!)}>
                Read latest dossier <ArrowRight size={17} />
              </button>
              <span>
                {dateTime(reading.dossierArtifact.created_at)} ·{" "}
                {reading.sourceCheck === true
                  ? "Source checks passed; interpretation needs review"
                  : reading.sourceCheck === false
                    ? "Source checks found issues"
                    : "Source checks not recorded"}
              </span>
            </div>
          )}
          {!reading.dossierArtifact && summary && (
            <div className="investigation-reading-footer">
              <button onClick={() => onNavigate("activity")}>
                Inspect the research <ArrowRight size={17} />
              </button>
              <span>No structured dossier recorded</span>
            </div>
          )}
        </section>

        {(reading.hypothesis || summary || reading.dossierArtifact) && (
          <section
            className="investigation-question"
            aria-labelledby="question-heading"
          >
            <div className="investigation-section-top">
              <span className="investigation-kicker">THE QUESTION</span>
              {reading.hypothesis && (
                <button
                  className="text-button"
                  onClick={() => onOpen(reading.hypothesis!)}
                >
                  View hypothesis <ArrowUpRight size={14} />
                </button>
              )}
            </div>
            <h2 id="question-heading">
              {reading.hypothesis?.title || "Research brief"}
            </h2>
            {text(hypothesis.status) && (
              <Status value={text(hypothesis.status)} />
            )}
            <p className="preserve-lines">
              {text(hypothesis.prediction) || data.hypothesis}
            </p>
            {text(hypothesis.disposition_reason) && (
              <div className="investigation-alternative">
                <span>Why this status</span>
                <p>{text(hypothesis.disposition_reason)}</p>
              </div>
            )}
            {text(hypothesis.competing_explanation) && (
              <div className="investigation-alternative">
                <span>Competing explanation</span>
                <p>{text(hypothesis.competing_explanation)}</p>
              </div>
            )}
            {text(hypothesis.falsification_rule) && (
              <div className="investigation-alternative">
                <span>What would disprove it</span>
                <p>{text(hypothesis.falsification_rule)}</p>
              </div>
            )}
          </section>
        )}

        {reading.claims.length > 0 && (
          <section
            className="investigation-section"
            aria-labelledby="findings-heading"
          >
            <div className="investigation-section-top">
              <div>
                <span className="investigation-kicker">
                  FROM THE LATEST DOSSIER
                </span>
                <h2 id="findings-heading">Findings to examine</h2>
              </div>
              <span className="investigation-count">
                {reading.claims.length} recorded
              </span>
            </div>
            <ol className="investigation-findings">
              {reading.claims.slice(0, 3).map((claim, index) => {
                const refs = records(claim.source_refs);
                const ids = [
                  ...new Set(
                    refs.map((ref) => text(ref.artifact_id)).filter(Boolean),
                  ),
                ];
                return (
                  <li key={text(claim.id) || index}>
                    <span className="investigation-finding-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <small>
                        {claim.kind === "inference"
                          ? "Inference"
                          : claim.kind === "fact"
                            ? "Source-reported claim"
                            : "Recorded claim"}
                      </small>
                      <p>{text(claim.statement)}</p>
                      <div className="investigation-citations">
                        {ids.slice(0, 3).map((id, i) => {
                          const source = reading.evidence.find(
                            (a) => a.id === id,
                          );
                          return (
                            <button
                              key={id}
                              disabled={loadingSource === id}
                              onClick={() =>
                                source ? onOpen(source) : onOpenSource(id)
                              }
                            >
                              <BookOpen size={12} />
                              {loadingSource === id
                                ? "Opening source…"
                                : source?.title || `Linked source ${i + 1}`}
                              <ArrowUpRight size={12} />
                            </button>
                          );
                        })}
                        {ids.length > 3 && (
                          <button
                            onClick={() => onOpen(reading.dossierArtifact!)}
                          >
                            All {ids.length} source references{" "}
                            <ArrowUpRight size={12} />
                          </button>
                        )}
                      </div>
                      {!ids.length && (
                        <span className="investigation-unresolved">
                          No source reference recorded
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
            {reading.claims.length > 3 && (
              <button
                className="text-button"
                onClick={() => onOpen(reading.dossierArtifact!)}
              >
                Read all {reading.claims.length} claims <ArrowRight size={14} />
              </button>
            )}
            <p className="investigation-footnote">
              Recorded claims are not independent verification of their
              conclusions.
            </p>
          </section>
        )}

        <section
          className="investigation-section investigation-work"
          aria-labelledby="work-heading"
        >
          <div className="investigation-section-top">
            <div>
              <span className="investigation-kicker">
                02 / THE RESEARCH TEAM
              </span>
              <h2 id="work-heading">
                {active.length ? "Work in motion" : "Research work"}
              </h2>
            </div>
            {data.tasks.length > 0 && (
              <button
                className="text-button"
                onClick={() => onNavigate("activity")}
              >
                Execution record <ArrowUpRight size={14} />
              </button>
            )}
          </div>
          <div className="investigation-work-status">
            <GitBranch size={16} />
            <span>
              {active.length
                ? `${active.length} active ${active.length === 1 ? "task" : "tasks"}`
                : data.tasks.length
                  ? "No tasks currently running"
                  : "No agent work has run yet"}
            </span>
            {failed.length > 0 && (
              <span className="investigation-unresolved">
                {failed.length} failed or blocked
              </span>
            )}
          </div>
          {data.tasks.length ? (
            children
          ) : (
            <p className="investigation-empty">
              When research runs, the coordinator’s assignments, specialist
              findings and tool calls will appear here. Existing source records
              remain available to inspect.
            </p>
          )}
          {data.tasks.length > 0 && (
            <details className="investigation-run-details">
              <summary>Run resources</summary>
              <span>
                {data.tool_calls_used} of {data.tool_budget} shared tool calls
                used · {data.tasks.length} recorded tasks
              </span>
            </details>
          )}
        </section>
      </div>

      <aside className="investigation-sidebar">
        <section
          className="investigation-open-questions"
          aria-labelledby="questions-heading"
        >
          <ArrowDownRight size={26} strokeWidth={1.5} />
          <span className="investigation-kicker">KEEP IN VIEW</span>
          <h2 id="questions-heading">What’s still open</h2>
          {hasQuestions ? (
            <ul>
              {reading.missing.slice(0, 3).map((item, i) => (
                <li key={`missing-${i}`}>
                  <strong>{text(item.field) || "Missing evidence"}</strong>
                  <p>{text(item.reason)}</p>
                  {text(item.consequence) && (
                    <span>{text(item.consequence)}</span>
                  )}
                </li>
              ))}
              {reading.uncertainty
                .slice(0, Math.max(0, 3 - reading.missing.length))
                .map((item, i) => (
                  <li key={`uncertain-${i}`}>
                    <p>{item}</p>
                  </li>
                ))}
            </ul>
          ) : (
            <p>
              {reading.dossierArtifact
                ? "No open questions were recorded in this dossier. That does not establish completeness."
                : "Open questions and missing evidence have not been recorded yet."}
            </p>
          )}
          {reading.dossierArtifact && (
            <button onClick={() => onOpen(reading.dossierArtifact!)}>
              Inspect uncertainties <ArrowRight size={15} />
            </button>
          )}
        </section>
        <section
          className="investigation-source-shelf"
          aria-labelledby="sources-heading"
        >
          <div className="investigation-section-top">
            <h2 id="sources-heading">Evidence on the desk</h2>
            <span className="investigation-count">
              {reading.evidence.length}
            </span>
          </div>
          <p className="investigation-footnote">
            {reading.sharedSourceIds.length
              ? `${reading.sharedSourceIds.length} additional ${reading.sharedSourceIds.length === 1 ? "source is" : "sources are"} linked from outside this case. Open them from the findings.`
              : "Sources linked to the visible findings appear first."}
          </p>
          {reading.evidence.length ? (
            reading.evidence
              .slice(0, 4)
              .map((a) => (
                <RecordLink key={a.id} artifact={a} onOpen={onOpen} />
              ))
          ) : (
            <p className="investigation-empty">
              {reading.sharedSourceIds.length
                ? "No source records are stored directly in this case."
                : "No sources have been saved for this investigation."}
            </p>
          )}
          {reading.evidence.length > 4 && (
            <button
              className="text-button"
              onClick={() => onNavigate("evidence")}
            >
              All {reading.evidence.length} sources <ArrowRight size={14} />
            </button>
          )}
        </section>
        <section
          className="investigation-source-shelf"
          aria-labelledby="analysis-heading"
        >
          <div className="investigation-section-top">
            <h2 id="analysis-heading">Analysis & review</h2>
            <span className="investigation-count">
              {reading.analyses.length}
            </span>
          </div>
          {reading.analyses.length ? (
            reading.analyses
              .slice(0, 4)
              .map((a) => (
                <RecordLink key={a.id} artifact={a} onOpen={onOpen} />
              ))
          ) : (
            <p className="investigation-empty">
              No computation, review or paper proposal is recorded yet.
            </p>
          )}
          {reading.analyses.length > 4 && (
            <button
              className="text-button"
              onClick={() => onNavigate("artifacts")}
            >
              All research records <ArrowRight size={14} />
            </button>
          )}
        </section>
        <div className="investigation-status-note">
          <Status value={data.status} />
          <span>
            Case status describes execution, not the strength of the thesis.
          </span>
        </div>
      </aside>
    </div>
  );
}
