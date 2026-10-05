export type Json =
  null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
export type CaseStatus =
  | "draft"
  | "queued"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "cancelled";
export const ARTIFACT_KINDS = [
  "evidence",
  "dataset",
  "code",
  "experiment",
  "review",
  "note",
  "paper_intent",
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
] as const;
export type ArtifactKind = (typeof ARTIFACT_KINDS)[number] | (string & {});

export interface Capabilities {
  execution_mode: "paper";
  read_only: boolean;
  authenticated?: boolean;
  authentication_required?: boolean;
  provider: { name: string; model: string; configured: boolean };
  sandbox: { available: boolean; reason: string | null };
  worker: { last_seen_at: string | null; active: boolean };
  tools: Json[];
  limitations: string[];
}
export interface Workspace {
  id: string;
  name: string;
  description: string;
}
export interface ResearchCase {
  id: string;
  title: string;
  hypothesis: string;
  workspace_id: string;
  status: CaseStatus;
  summary: string | null;
  tool_budget: number;
  tool_calls_used: number;
  created_at: string;
  updated_at: string;
}
export interface Task {
  id: string;
  case_id: string;
  parent_id: string | null;
  role: string;
  instruction: string;
  status: string;
  artifact_ids: string[];
  attempt: number;
  result: Json;
  error: Json;
  summary: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
export interface Artifact {
  id: string;
  case_id: string;
  task_id: string | null;
  kind: ArtifactKind;
  title: string;
  content: Json;
  sha256: string;
  metadata: JsonObject;
  created_at: string;
  score?: number;
}
export interface ToolCall {
  id: string;
  task_id: string;
  call_id: string;
  name: string;
  arguments: Json;
  status: string;
  result: Json;
  error: Json;
  duration_ms: number | null;
  started_at: string;
  finished_at: string | null;
}
export interface ResearchEvent {
  seq: number;
  case_id: string;
  task_id: string | null;
  kind: string;
  data: JsonObject;
  created_at: string;
}
export interface CaseDetail extends ResearchCase {
  tasks: Task[];
  artifacts: Artifact[];
  tool_calls: ToolCall[];
  events: ResearchEvent[];
}
export interface PaperPortfolio {
  account_id: string | null;
  cash: string;
  equity: string | null;
  realized_pnl: string;
  valuation_basis?: string;
  initialized?: boolean;
  positions: JsonObject[];
  events: JsonObject[];
  currency: "USD";
  execution_mode: "paper";
}

export class ContractError extends Error {
  constructor(field: string) {
    super(
      `The research API returned an invalid ${field}. Please refresh or check the server version.`,
    );
    this.name = "ContractError";
  }
}
export function object(
  value: unknown,
  field = "response",
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ContractError(field);
  return value as Record<string, unknown>;
}
function string(value: unknown, field: string): string {
  if (typeof value !== "string") throw new ContractError(field);
  return value;
}
function nullableString(value: unknown, field: string): string | null {
  return value == null ? null : string(value, field);
}
function number(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value))
    throw new ContractError(field);
  return value;
}
function boolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new ContractError(field);
  return value;
}
function array<T>(
  value: unknown,
  parse: (v: unknown) => T,
  field: string,
): T[] {
  if (!Array.isArray(value)) throw new ContractError(field);
  return value.map(parse);
}
export function json(value: unknown): Json {
  if (value == null) return null;
  if (typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map(json);
  const record = object(value, "JSON value");
  return Object.fromEntries(
    Object.entries(record).map(([k, v]) => [k, json(v)]),
  );
}
export function jsonObject(value: unknown): JsonObject {
  return json(object(value)) as JsonObject;
}
export function parseList<T>(parse: (v: unknown) => T): (v: unknown) => T[] {
  return (value) => array(object(value).items, parse, "list");
}
export function parseCapabilities(value: unknown): Capabilities {
  const v = object(value),
    p = object(v.provider, "provider"),
    s = object(v.sandbox, "sandbox"),
    w = object(v.worker, "worker");
  if (v.execution_mode !== "paper") throw new ContractError("execution mode");
  return {
    execution_mode: "paper",
    read_only: boolean(v.read_only, "read-only flag"),
    ...(v.authenticated === undefined
      ? {}
      : { authenticated: boolean(v.authenticated, "authentication state") }),
    ...(v.authentication_required === undefined
      ? {}
      : {
          authentication_required: boolean(
            v.authentication_required,
            "authentication requirement",
          ),
        }),
    provider: {
      name: string(p.name, "provider name"),
      model: string(p.model, "model name"),
      configured: boolean(p.configured, "provider state"),
    },
    sandbox: {
      available: boolean(s.available, "sandbox state"),
      reason: nullableString(s.reason, "sandbox reason"),
    },
    worker: {
      active: boolean(w.active, "worker state"),
      last_seen_at: nullableString(w.last_seen_at, "worker timestamp"),
    },
    tools: array(v.tools, json, "tools"),
    limitations: array(
      v.limitations,
      (x) => string(x, "limitation"),
      "limitations",
    ),
  };
}
export function parseWorkspace(value: unknown): Workspace {
  const v = object(value);
  return {
    id: string(v.id, "workspace id"),
    name: string(v.name, "workspace name"),
    description: string(v.description, "workspace description"),
  };
}
const CASE_STATUSES = new Set([
  "draft",
  "queued",
  "running",
  "waiting",
  "completed",
  "failed",
  "cancelled",
]);
export function parseCase(value: unknown): ResearchCase {
  const v = object(value);
  if (!CASE_STATUSES.has(String(v.status)))
    throw new ContractError("case status");
  return {
    id: string(v.id, "case id"),
    title: string(v.title, "case title"),
    hypothesis: string(v.hypothesis, "hypothesis"),
    workspace_id: string(v.workspace_id, "workspace id"),
    status: v.status as CaseStatus,
    summary: nullableString(v.summary, "summary"),
    tool_budget: number(v.tool_budget, "tool budget"),
    tool_calls_used: number(v.tool_calls_used, "tool usage"),
    created_at: string(v.created_at, "creation date"),
    updated_at: string(v.updated_at, "update date"),
  };
}
export function parseTask(value: unknown): Task {
  const v = object(value);
  return {
    id: string(v.id, "task id"),
    case_id: string(v.case_id, "case id"),
    parent_id: nullableString(v.parent_id, "parent task"),
    role: string(v.role, "task role"),
    instruction: string(v.instruction, "task instruction"),
    status: string(v.status, "task status"),
    artifact_ids: array(
      v.artifact_ids,
      (x) => string(x, "artifact id"),
      "artifact ids",
    ),
    attempt: number(v.attempt, "attempt"),
    result: json(v.result),
    error: json(v.error),
    summary: nullableString(v.summary, "task summary"),
    created_at: string(v.created_at, "task date"),
    started_at: nullableString(v.started_at, "task start"),
    finished_at: nullableString(v.finished_at, "task finish"),
  };
}
export function parseArtifact(value: unknown): Artifact {
  const v = object(value);
  if (typeof v.kind !== "string" || !/^[a-z][a-z0-9_]{0,79}$/.test(v.kind))
    throw new ContractError("artifact kind");
  return {
    id: string(v.id, "artifact id"),
    case_id: string(v.case_id, "artifact case"),
    task_id: nullableString(v.task_id, "artifact task"),
    kind: v.kind as ArtifactKind,
    title: string(v.title, "artifact title"),
    content: json(v.content),
    sha256: string(v.sha256, "content hash"),
    metadata: jsonObject(v.metadata),
    created_at: string(v.created_at, "artifact date"),
    ...(v.score == null ? {} : { score: number(v.score, "retrieval score") }),
  };
}
export function parseToolCall(value: unknown): ToolCall {
  const v = object(value);
  return {
    id: string(v.id, "tool call id"),
    task_id: string(v.task_id, "tool task"),
    call_id: string(v.call_id, "provider call id"),
    name: string(v.name, "tool name"),
    arguments: json(v.arguments),
    status: string(v.status, "tool status"),
    result: json(v.result),
    error: json(v.error),
    duration_ms:
      v.duration_ms == null ? null : number(v.duration_ms, "tool duration"),
    started_at: string(v.started_at, "tool start"),
    finished_at: nullableString(v.finished_at, "tool finish"),
  };
}
export function parseEvent(value: unknown): ResearchEvent {
  const v = object(value);
  return {
    seq: number(v.seq, "event sequence"),
    case_id: string(v.case_id, "event case"),
    task_id: nullableString(v.task_id, "event task"),
    kind: string(v.kind, "event kind"),
    data: jsonObject(v.data),
    created_at: string(v.created_at, "event date"),
  };
}
export function parseEvents(value: unknown): {
  items: ResearchEvent[];
  cursor: number;
} {
  const v = object(value);
  return {
    items: array(v.items, parseEvent, "events"),
    cursor: number(v.cursor, "event cursor"),
  };
}
export function parseCaseDetail(value: unknown): CaseDetail {
  const v = object(value);
  return {
    ...parseCase(v),
    tasks: array(v.tasks, parseTask, "tasks"),
    artifacts: array(v.artifacts, parseArtifact, "artifacts"),
    tool_calls: array(v.tool_calls, parseToolCall, "tool calls"),
    events: array(v.events, parseEvent, "events"),
  };
}
function decimal(value: unknown, field: string): string {
  const s = string(value, field);
  if (!/^-?\d+(\.\d+)?$/.test(s)) throw new ContractError(field);
  return s;
}
export function parsePortfolio(value: unknown): PaperPortfolio {
  const v = object(value);
  if (v.execution_mode !== "paper" || v.currency !== "USD")
    throw new ContractError("portfolio mode or currency");
  return {
    account_id: nullableString(v.account_id, "account id"),
    cash: decimal(v.cash, "cash"),
    equity: v.equity == null ? null : decimal(v.equity, "equity"),
    realized_pnl: decimal(v.realized_pnl, "realized P&L"),
    positions: array(v.positions, jsonObject, "positions"),
    events: array(v.events, jsonObject, "ledger events"),
    currency: "USD",
    execution_mode: "paper",
    ...(typeof v.initialized === "boolean"
      ? { initialized: v.initialized }
      : {}),
    ...(typeof v.valuation_basis === "string"
      ? { valuation_basis: v.valuation_basis }
      : {}),
  };
}
export const parseCases = parseList(parseCase);
export const parseArtifacts = parseList(parseArtifact);
export const parseWorkspaces = parseList(parseWorkspace);
