"use client";
import Link from "next/link";
import {
  ArrowUpRight,
  Code2,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  ShieldCheck,
  Stethoscope,
  Lightbulb,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { Artifact, Json, JsonObject } from "@/lib/contracts";
import {
  dateTime,
  displayJson,
  isRecord,
  label,
  money,
  relativeTime,
  scalar,
} from "@/lib/format";
import {
  DownloadButton,
  JsonDetails,
  Modal,
  SourceLink,
  Status,
  StructuredValues,
} from "./ui";
import { ResearchArtifactContent } from "./research-artifacts";
import { StrategyAssessment } from "./strategy-assessment";

export const artifactIcons: Partial<Record<string, LucideIcon>> = {
  evidence: FileText,
  dataset: Database,
  code: Code2,
  experiment: FlaskConical,
  strategy_assessment: ShieldCheck,
  review: ShieldCheck,
  note: FileText,
  paper_intent: GitBranch,
  clinical_dossier: Stethoscope,
  hypothesis: Lightbulb,
  evaluation_reference: FileText,
  evaluation_report: FlaskConical,
  specialist_spec: Users,
  specialist_activation: Users,
  research_tool_spec: Wrench,
  research_tool_tests: FlaskConical,
  research_tool_qualification: ShieldCheck,
  research_tool_result: Wrench,
};
export function ArtifactCard({
  artifact,
  onOpen,
}: {
  artifact: Artifact;
  onOpen: (artifact: Artifact) => void;
}) {
  const Icon = artifactIcons[artifact.kind] ?? FileText;
  const content = isRecord(artifact.content) ? artifact.content : null;
  return (
    <button className="artifact-card" onClick={() => onOpen(artifact)}>
      <div className={`artifact-icon artifact-icon-${artifact.kind}`}>
        <Icon size={19} strokeWidth={1.6} />
      </div>
      <div className="artifact-card-main">
        <span className="small-caps">{label(artifact.kind)}</span>
        <h3>{artifact.title}</h3>
        <div className="artifact-card-meta">
          <span>{relativeTime(artifact.created_at)}</span>
          <span className="mono">{artifact.sha256.slice(0, 8)}</span>
        </div>
      </div>
      {typeof content?.verdict === "string" ? (
        <Status value={content.verdict} />
      ) : (
        <ArrowUpRight size={16} className="muted" />
      )}
    </button>
  );
}

const fractionMetrics = new Set([
  "net_return",
  "max_drawdown",
  "geometrically_linked_fold_return",
  "training_net_return",
]);
const moneyMetrics = new Set([
  "initial_cash",
  "final_equity",
  "fees",
  "turnover_notional",
  "realized_pnl",
  "unrealized_pnl",
]);
export function metricValue(name: string, value: Json): string {
  if (value == null) return "—";
  const numeric =
    (typeof value === "number" ||
      (typeof value === "string" && value.trim() !== "")) &&
    Number.isFinite(Number(value));
  if (name === "excess_return_vs_buy_hold" && numeric)
    return `${(Number(value) * 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} pp`;
  if (name === "sharpe" && numeric)
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  if (fractionMetrics.has(name) && numeric)
    return `${(Number(value) * 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
  if (moneyMetrics.has(name))
    return money(
      typeof value === "string" || typeof value === "number" ? value : null,
    );
  return scalar(value);
}
export function ExperimentContent({ content }: { content: Json }) {
  if (!isRecord(content)) return <JsonDetails value={content} open />;
  const metrics = isRecord(content.metrics) ? content.metrics : {};
  const primary = [
    "net_return" in metrics ? "net_return" : "geometrically_linked_fold_return",
    "final_equity",
    "max_drawdown",
    "sharpe",
    "fees",
    "fill_count" in metrics ? "fill_count" : "fold_count",
  ].filter((key) => key in metrics);
  const secondary = Object.keys(metrics).filter(
    (key) => !primary.includes(key),
  );
  const metricLabels: Record<string, string> = {
    fees: "Trading fees",
    fill_count: "Fills",
    geometrically_linked_fold_return: "Linked fold return",
    fold_count: "Folds",
  };
  const points = Array.isArray(content.equity_curve)
    ? content.equity_curve.filter(isRecord)
    : [];
  const folds = Array.isArray(content.folds)
    ? content.folds.filter(isRecord)
    : [];
  return (
    <div className="experiment-content">
      <StrategyAssessment value={content.assessment} />
      {typeof content.status === "string" && <Status value={content.status} />}
      {primary.length > 0 && (
        <div
          className="experiment-metrics"
          role="group"
          aria-label="Key experiment metrics"
        >
          {primary.map((key) => (
            <div key={key}>
              <span>{metricLabels[key] ?? label(key)}</span>
              <strong
                className={
                  [
                    "net_return",
                    "geometrically_linked_fold_return",
                    "sharpe",
                  ].includes(key) && Number(metrics[key]) < 0
                    ? "metric-negative"
                    : undefined
                }
              >
                {metricValue(key, metrics[key])}
              </strong>
            </div>
          ))}
        </div>
      )}
      {points.length > 1 && <EquityChart points={points} />}
      {isRecord(content.baseline) && (
        <section className="result-section">
          <h3>Baseline comparison</h3>
          {Object.entries(content.baseline).map(([name, values]) => (
            <div className="baseline-row" key={name}>
              <strong>{label(name)}</strong>
              {isRecord(values) ? (
                <span>
                  {"net_return" in values &&
                    `${metricValue("net_return", values.net_return)} return`}
                  {"final_equity" in values &&
                    ` · ${metricValue("final_equity", values.final_equity)} equity`}
                </span>
              ) : (
                <span>{scalar(values)}</span>
              )}
            </div>
          ))}
          {"excess_return_vs_buy_hold" in metrics && (
            <div className="baseline-row">
              <strong>Strategy vs. buy and hold</strong>
              <span>
                {metricValue(
                  "excess_return_vs_buy_hold",
                  metrics.excess_return_vs_buy_hold,
                )}
              </span>
            </div>
          )}
        </section>
      )}
      {folds.length > 0 && (
        <section className="result-section">
          <h3>Walk-forward folds</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Fold</th>
                  <th>Training period</th>
                  <th>Test period</th>
                  <th>Return</th>
                </tr>
              </thead>
              <tbody>
                {folds.map((fold, index) => (
                  <tr key={index}>
                    <td>{scalar(fold.index ?? index + 1)}</td>
                    <td>
                      {scalar(fold.train_start)} → {scalar(fold.train_end)}
                    </td>
                    <td>
                      {scalar(fold.test_start)} → {scalar(fold.test_end)}
                    </td>
                    <td>
                      {isRecord(fold.metrics)
                        ? metricValue("net_return", fold.metrics.net_return)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {secondary.length > 0 && (
        <details className="json-details metric-diagnostics">
          <summary>Metric diagnostics and assumptions</summary>
          <dl className="structured-values">
            {secondary.map((key) => (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>{metricValue(key, metrics[key])}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {content.validation != null && (
        <JsonDetails title="Validation checks" value={content.validation} />
      )}
      {content.spec != null && (
        <JsonDetails title="Experiment specification" value={content.spec} />
      )}
      {Array.isArray(content.trades) && (
        <JsonDetails
          title={`Inspect ${content.trades.length} simulated trades`}
          value={content.trades}
        />
      )}
      <JsonDetails title="Complete experiment output" value={content} />
    </div>
  );
}
export function EquityChart({ points }: { points: JsonObject[] }) {
  const valid = points.filter(
    (p) =>
      (typeof p.equity === "string" || typeof p.equity === "number") &&
      Number.isFinite(Number(p.equity)),
  );
  if (valid.length < 2) return null;
  const values = valid.map((p) => Number(p.equity));
  const minimum = Math.min(...values),
    maximum = Math.max(...values),
    padding = (maximum - minimum) * 0.12 || Math.max(maximum * 0.01, 1);
  const low = minimum - padding,
    high = maximum + padding;
  const x = (i: number) => 60 + (i / (valid.length - 1)) * 590;
  const y = (v: number) => 24 + ((high - v) / (high - low)) * 154;
  const path = values
    .map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`)
    .join(" ");
  return (
    <figure className="equity-chart">
      <figcaption>
        <strong>Simulated equity</strong>
        <span>{valid.length} recorded sessions · USD</span>
      </figcaption>
      <svg
        viewBox="0 0 680 215"
        role="img"
        aria-label={`Simulated equity from ${money(values[0])} to ${money(values[values.length - 1])} across ${valid.length} sessions`}
      >
        <defs>
          <linearGradient id="equity-shade" x1="0" x2="0" y1="0" y2="1">
            <stop stopColor="#247769" stopOpacity="0.16" />
            <stop offset="1" stopColor="#247769" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((ratio) => {
          const value = low + (high - low) * ratio;
          return (
            <g key={ratio}>
              <line
                x1="60"
                x2="650"
                y1={y(value)}
                y2={y(value)}
                stroke="#e5e9e6"
              />
              <text x="50" y={y(value) + 4} textAnchor="end">
                {new Intl.NumberFormat("en", {
                  notation: "compact",
                  maximumFractionDigits: 1,
                }).format(value)}
              </text>
            </g>
          );
        })}
        <path d={`${path} L650,180 L60,180 Z`} fill="url(#equity-shade)" />
        <path
          d={path}
          fill="none"
          stroke="#247769"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <text x="60" y="205">
          {scalar(valid[0].session)}
        </text>
        <text x="650" y="205" textAnchor="end">
          {scalar(valid[valid.length - 1].session)}
        </text>
      </svg>
    </figure>
  );
}
export function ReviewContent({ content }: { content: Json }) {
  if (!isRecord(content)) return <JsonDetails value={content} open />;
  const findings = Array.isArray(content.findings) ? content.findings : [];
  return (
    <div className="review-content">
      {typeof content.verdict === "string" && (
        <div className="review-verdict">
          <ShieldCheck size={20} />
          <span>Reviewer verdict</span>
          <Status value={content.verdict} />
        </div>
      )}
      {findings.length > 0 && (
        <div className="findings-list">
          {findings.map((finding, i) => (
            <div className="finding" key={i}>
              <span className="finding-number">
                {String(i + 1).padStart(2, "0")}
              </span>
              {isRecord(finding) ? (
                <div>
                  {typeof finding.severity === "string" && (
                    <span className="small-caps">{finding.severity}</span>
                  )}
                  <p>
                    {scalar(
                      finding.message ??
                        finding.description ??
                        finding.finding ??
                        finding.title ??
                        finding,
                    )}
                  </p>
                  {Object.keys(finding).length > 2 && (
                    <JsonDetails title="Finding details" value={finding} />
                  )}
                </div>
              ) : (
                <p>{scalar(finding)}</p>
              )}
            </div>
          ))}
        </div>
      )}
      {typeof content.summary === "string" && (
        <p className="prose">{content.summary}</p>
      )}
      {typeof content.artifact_sha256 === "string" && (
        <div className="review-binding">
          <span>Reviewed artifact hash</span>
          <code>{content.artifact_sha256}</code>
        </div>
      )}
      <JsonDetails title="Review record and bindings" value={content} />
    </div>
  );
}
export function ArtifactContent({ artifact }: { artifact: Artifact }) {
  if (artifact.kind === "strategy_assessment")
    return <StrategyAssessment value={artifact.content} />;
  if (
    [
      "clinical_dossier",
      "hypothesis",
      "evaluation_reference",
      "evaluation_report",
      "specialist_spec",
      "specialist_activation",
      "research_tool_spec",
      "research_tool_tests",
      "research_tool_qualification",
      "research_tool_result",
    ].includes(artifact.kind)
  )
    return (
      <ResearchArtifactContent
        kind={artifact.kind}
        content={artifact.content}
      />
    );
  if (artifact.kind === "experiment")
    return <ExperimentContent content={artifact.content} />;
  if (artifact.kind === "review")
    return <ReviewContent content={artifact.content} />;
  const content = artifact.content;
  if (artifact.kind === "code") {
    const code = isRecord(content)
      ? (content.code ?? content.source ?? content)
      : content;
    return <pre className="code-view">{displayJson(code)}</pre>;
  }
  if (typeof content === "string")
    return <div className="prose preserve-lines">{content}</div>;
  if (isRecord(content))
    return (
      <>
        <StructuredValues value={content} />
        {typeof content.url === "string" && <SourceLink url={content.url} />}
        <JsonDetails
          title="Full artifact content"
          value={content}
          open={Object.keys(content).length < 5}
        />
      </>
    );
  return <JsonDetails value={content} open />;
}
export function ArtifactModal({
  artifact,
  onClose,
}: {
  artifact: Artifact;
  onClose: () => void;
}) {
  const Icon = artifactIcons[artifact.kind] ?? FileText;
  return (
    <Modal title={artifact.title} onClose={onClose} wide>
      <div className="artifact-modal-meta">
        <span className="artifact-kind">
          <Icon size={15} />
          {label(artifact.kind)}
        </span>
        <span>{dateTime(artifact.created_at)}</span>
        <DownloadButton
          name={`${artifact.kind}-${artifact.id}.json`}
          value={artifact}
        />
      </div>
      <div className="modal-body">
        <ArtifactContent artifact={artifact} />
        <div className="artifact-provenance">
          <h3>Provenance</h3>
          <dl>
            <div>
              <dt>Investigation</dt>
              <dd>
                <Link href={`/cases/${artifact.case_id}`} onClick={onClose}>
                  Open research case
                  <ArrowUpRight size={13} />
                </Link>
              </dd>
            </div>
            <div>
              <dt>Content hash</dt>
              <dd className="mono break-all">{artifact.sha256}</dd>
            </div>
            <div>
              <dt>Producing task</dt>
              <dd className="mono">
                {artifact.task_id ||
                  (artifact.kind === "strategy_assessment"
                    ? "System assessment"
                    : "Uploaded artifact")}
              </dd>
            </div>
          </dl>
          <JsonDetails
            title="Source metadata and input versions"
            value={artifact.metadata}
          />
        </div>
      </div>
    </Modal>
  );
}
