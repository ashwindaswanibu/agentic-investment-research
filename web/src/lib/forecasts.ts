import {
  ContractError,
  object,
  parseArtifact,
  type Artifact,
} from "./contracts";

export interface ForecastReceipt {
  id: string;
  sha256: string;
  title: string;
  kind: string;
}
export interface ForecastCitation {
  artifact_id: string;
  artifact_sha256: string;
  excerpt: string;
  source_path?: string | null;
}
export interface ForecastContent {
  question: string;
  hypothesis: ForecastReceipt;
  opens_at: string;
  closes_at: string;
  registered_at: string;
  yes_rule: string;
  no_rule: string;
  unresolvable_rule: string;
  resolution_source: string;
  status: "forecast" | "abstain";
  probability: number | null;
  abstention_reason: string | null;
  baseline_probability: number;
  baseline_rationale: string;
  source_refs: ForecastReceipt[];
  synthetic: boolean;
}
export interface ResolutionContent {
  outcome: "yes" | "no" | "unresolvable";
  rationale: string;
  source_refs: ForecastCitation[];
  recorded_at: string;
  previous_resolution_id: string | null;
  synthetic: boolean;
}
export interface ForecastRecord {
  forecast: Artifact;
  content: ForecastContent;
  resolutions: Artifact[];
  latest_resolution: Artifact | null;
  assessment: {
    status: "pending" | "due" | "resolved" | "unresolvable" | "abstained";
    scored: boolean;
    brier: number | null;
    baseline_brier: number | null;
    improvement: number | null;
  };
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim())
    throw new ContractError(field);
  return value;
}
function probability(value: unknown, field: string): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < 0 ||
    value > 1
  )
    throw new ContractError(field);
  return value;
}
function timestamp(value: unknown, field: string): string {
  const result = text(value, field);
  if (!Number.isFinite(Date.parse(result))) throw new ContractError(field);
  return result;
}
function flag(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new ContractError(field);
  return value;
}
function list<T>(
  value: unknown,
  parse: (item: unknown) => T,
  field: string,
): T[] {
  if (!Array.isArray(value)) throw new ContractError(field);
  return value.map(parse);
}
function receipt(value: unknown): ForecastReceipt {
  const v = object(value, "forecast source");
  return {
    id: text(v.id, "source ID"),
    sha256: text(v.sha256, "source hash"),
    title: text(v.title, "source title"),
    kind: text(v.kind, "source kind"),
  };
}
export function parseForecastContent(value: unknown): ForecastContent {
  const v = object(value, "forecast content");
  if (v.status !== "forecast" && v.status !== "abstain")
    throw new ContractError("forecast status");
  if (v.status === "abstain" && v.probability !== null)
    throw new ContractError("abstention probability");
  return {
    question: text(v.question, "forecast question"),
    hypothesis: receipt(v.hypothesis),
    opens_at: timestamp(v.opens_at, "event window start"),
    closes_at: timestamp(v.closes_at, "event window end"),
    registered_at: timestamp(v.registered_at, "registration time"),
    yes_rule: text(v.yes_rule, "yes rule"),
    no_rule: text(v.no_rule, "no rule"),
    unresolvable_rule: text(v.unresolvable_rule, "unresolvable rule"),
    resolution_source: text(v.resolution_source, "resolution source"),
    status: v.status,
    probability:
      v.status === "abstain"
        ? null
        : probability(v.probability, "forecast probability"),
    abstention_reason:
      v.status === "abstain"
        ? text(v.abstention_reason, "abstention reason")
        : null,
    baseline_probability: probability(
      v.baseline_probability,
      "baseline probability",
    ),
    baseline_rationale: text(v.baseline_rationale, "baseline rationale"),
    source_refs: list(v.source_refs, receipt, "forecast sources"),
    synthetic: flag(v.synthetic, "synthetic flag"),
  };
}
export function parseResolutionContent(value: unknown): ResolutionContent {
  const v = object(value, "resolution content");
  if (!["yes", "no", "unresolvable"].includes(String(v.outcome)))
    throw new ContractError("resolution outcome");
  return {
    outcome: v.outcome as ResolutionContent["outcome"],
    rationale: text(v.rationale, "resolution rationale"),
    recorded_at: timestamp(v.recorded_at, "resolution time"),
    previous_resolution_id:
      v.previous_resolution_id == null
        ? null
        : text(v.previous_resolution_id, "previous resolution"),
    synthetic: flag(v.synthetic, "synthetic resolution flag"),
    source_refs: list(
      v.source_refs,
      (source) => {
        const ref = object(source, "resolution citation");
        if (ref.source_path != null && typeof ref.source_path !== "string")
          throw new ContractError("citation path");
        return {
          artifact_id: text(ref.artifact_id, "citation artifact ID"),
          artifact_sha256: text(ref.artifact_sha256, "citation hash"),
          excerpt: text(ref.excerpt, "citation excerpt"),
          source_path: ref.source_path as string | null | undefined,
        };
      },
      "resolution citations",
    ),
  };
}
export function parseForecasts(value: unknown): ForecastRecord[] {
  return list(
    object(value).items,
    (item) => {
      const v = object(item, "forecast record"),
        assessment = object(v.assessment, "forecast assessment");
      const forecast = parseArtifact(v.forecast);
      if (forecast.kind !== "forecast")
        throw new ContractError("forecast artifact kind");
      const resolutions = list(
        v.resolutions,
        (entry) => {
          const artifact = parseArtifact(entry);
          if (artifact.kind !== "forecast_resolution")
            throw new ContractError("resolution artifact kind");
          parseResolutionContent(artifact.content);
          return artifact;
        },
        "resolution history",
      );
      const latest =
        v.latest_resolution == null ? null : parseArtifact(v.latest_resolution);
      if (
        latest &&
        !resolutions.some(
          (r) => r.id === latest.id && r.sha256 === latest.sha256,
        )
      )
        throw new ContractError("latest resolution reference");
      if (
        !["pending", "due", "resolved", "unresolvable", "abstained"].includes(
          String(assessment.status),
        )
      )
        throw new ContractError("forecast assessment status");
      const scored = flag(assessment.scored, "forecast scoring state");
      const nullableScore = (name: string) =>
        assessment[name] == null ? null : probability(assessment[name], name);
      const brier = nullableScore("brier"),
        baseline_brier = nullableScore("baseline_brier");
      const improvement = assessment.improvement;
      if (
        improvement != null &&
        (typeof improvement !== "number" ||
          !Number.isFinite(improvement) ||
          Math.abs(improvement) > 1)
      )
        throw new ContractError("baseline improvement");
      if (
        scored &&
        (brier == null || baseline_brier == null || improvement == null)
      )
        throw new ContractError("forecast scores");
      return {
        forecast,
        content: parseForecastContent(forecast.content),
        resolutions,
        latest_resolution: latest,
        assessment: {
          status: assessment.status as ForecastRecord["assessment"]["status"],
          scored,
          brier,
          baseline_brier,
          improvement: improvement as number | null,
        },
      };
    },
    "forecast list",
  );
}

export function utcDate(value: string): string {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? `${date.toISOString().replace("T", " ").slice(0, 19)} UTC`
    : "Invalid date";
}

export function localDateToISO(value: string): string {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime()))
    throw new Error("Enter a valid event window in your local time zone.");
  return date.toISOString();
}

export function sortForecasts(items: ForecastRecord[]): ForecastRecord[] {
  const order = {
    due: 0,
    pending: 1,
    abstained: 2,
    unresolvable: 3,
    resolved: 4,
  };
  return [...items].sort(
    (a, b) =>
      order[a.assessment.status] - order[b.assessment.status] ||
      a.content.closes_at.localeCompare(b.content.closes_at) ||
      a.forecast.id.localeCompare(b.forecast.id),
  );
}
