import {
  ContractError,
  jsonObject,
  object,
  type JsonObject,
} from "./contracts";

export type OperationMode = "active" | "exit_only" | "halted";
export interface PaperMandatePayload {
  name: string;
  allowed_symbols: string[];
  policy: {
    max_symbol_weight: string;
    max_order_notional: string;
    max_quote_age_seconds: number;
    fee_bps: string;
  };
  max_open_orders: number;
  order_ttl_seconds: number;
  max_decision_age_seconds: number;
  poll_interval_seconds: number;
  max_drawdown_amount: string;
  expires_at: string;
}
export interface PaperMandate {
  id: string;
  payload: PaperMandatePayload;
  sha256: string;
  created_at: string;
}
export interface OperationsControl {
  version: number;
  mode: OperationMode;
  mandate_id: string | null;
}
export interface PaperPerformance {
  equity_series: JsonObject[];
  daily: JsonObject[];
  latest: JsonObject | null;
  methodology?: JsonObject;
  as_of?: string | null;
  report_as_of?: string | null;
  calendar_coverage?: {
    complete: boolean;
    start: string | null;
    end: string | null;
    verified_at: string | null;
    reason: string | null;
  };
  window?: { days: number; max_observations: number; truncated: boolean };
}
export interface PaperOperations {
  control: OperationsControl;
  mandate: PaperMandate | null;
  mandates?: PaperMandate[];
  feed: { provider: string; configured: boolean; reason: string | null };
  worker: { active: boolean; last_seen_at: string | null };
  latest_observation: JsonObject | null;
  performance: PaperPerformance;
  limitations: string[];
  recent_actions?: JsonObject[];
  status?: JsonObject | string | null;
  drawdown?: { peak_equity: string | null; tripped: boolean };
  latest_tick?: {
    observed_at: string;
    status: string;
    actions: JsonObject[];
    error: { code: string; message: string } | null;
  } | null;
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim())
    throw new ContractError(field);
  return value;
}
function bool(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new ContractError(field);
  return value;
}
function integer(
  value: unknown,
  field: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  )
    throw new ContractError(field);
  return value;
}
function decimal(value: unknown, field: string): string {
  if (typeof value !== "string" || !/^\d+(\.\d+)?$/.test(value))
    throw new ContractError(field);
  return value;
}
function rows(value: unknown, field: string): JsonObject[] {
  if (!Array.isArray(value)) throw new ContractError(field);
  return value.map(jsonObject);
}
function nullableText(value: unknown, field: string): string | null {
  return value == null ? null : text(value, field);
}
function utc(value: unknown, field: string): string {
  const result = text(value, field);
  if (
    !/(Z|[+-]\d\d:\d\d)$/.test(result) ||
    !Number.isFinite(Date.parse(result))
  )
    throw new ContractError(field);
  return result;
}

export function parseMandate(value: unknown): PaperMandate {
  const row = object(value, "paper mandate"),
    payload = object(row.payload, "mandate payload"),
    policy = object(payload.policy, "mandate policy");
  if (
    !Array.isArray(payload.allowed_symbols) ||
    payload.allowed_symbols.length < 1 ||
    payload.allowed_symbols.length > 30
  )
    throw new ContractError("allowed symbols");
  return {
    id: text(row.id, "mandate id"),
    sha256: text(row.sha256, "mandate hash"),
    created_at: utc(row.created_at, "mandate creation time"),
    payload: {
      name: text(payload.name, "mandate name"),
      allowed_symbols: payload.allowed_symbols.map((symbol) =>
        text(symbol, "symbol"),
      ),
      policy: {
        max_symbol_weight: decimal(
          policy.max_symbol_weight,
          "maximum symbol weight",
        ),
        max_order_notional: decimal(
          policy.max_order_notional,
          "maximum order notional",
        ),
        max_quote_age_seconds: integer(
          policy.max_quote_age_seconds,
          "maximum quote age",
          1,
          60,
        ),
        fee_bps: decimal(policy.fee_bps, "fee basis points"),
      },
      max_open_orders: integer(
        payload.max_open_orders,
        "maximum open orders",
        1,
        20,
      ),
      order_ttl_seconds: integer(
        payload.order_ttl_seconds,
        "order lifetime",
        60,
        86400,
      ),
      max_decision_age_seconds: integer(
        payload.max_decision_age_seconds,
        "maximum decision age",
        60,
        86400,
      ),
      poll_interval_seconds: integer(
        payload.poll_interval_seconds,
        "poll interval",
        5,
        300,
      ),
      max_drawdown_amount: decimal(
        payload.max_drawdown_amount,
        "drawdown limit",
      ),
      expires_at: utc(payload.expires_at, "mandate expiry"),
    },
  };
}
export function parseOperationsControl(value: unknown): OperationsControl {
  const row = object(value, "operations control");
  if (!["active", "exit_only", "halted"].includes(String(row.mode)))
    throw new ContractError("operations mode");
  return {
    version: integer(row.version, "control version", 0),
    mode: row.mode as OperationMode,
    mandate_id: nullableText(row.mandate_id, "controlled mandate id"),
  };
}
export function parsePaperPerformance(value: unknown): PaperPerformance {
  const row = object(value, "paper performance");
  return {
    equity_series: rows(row.equity_series, "equity observations"),
    daily: rows(row.daily, "daily observations"),
    latest: row.latest == null ? null : jsonObject(row.latest),
    ...(row.methodology === undefined
      ? {}
      : { methodology: jsonObject(row.methodology) }),
    ...(row.as_of === undefined
      ? {}
      : { as_of: nullableText(row.as_of, "performance observation time") }),
    ...(row.report_as_of === undefined
      ? {}
      : {
          report_as_of: nullableText(
            row.report_as_of,
            "performance report time",
          ),
        }),
    ...(row.calendar_coverage === undefined
      ? {}
      : {
          calendar_coverage: (() => {
            const coverage = object(row.calendar_coverage, "calendar coverage");
            return {
              complete: bool(coverage.complete, "calendar completeness"),
              start: nullableText(coverage.start, "calendar start"),
              end: nullableText(coverage.end, "calendar end"),
              verified_at: nullableText(
                coverage.verified_at,
                "calendar verification time",
              ),
              reason: nullableText(coverage.reason, "calendar coverage reason"),
            };
          })(),
        }),
    ...(row.window === undefined
      ? {}
      : {
          window: (() => {
            const window = object(row.window, "performance window");
            return {
              days: integer(window.days, "performance window days", 1),
              max_observations: integer(
                window.max_observations,
                "performance observation limit",
                1,
              ),
              truncated: bool(
                window.truncated,
                "performance window truncation",
              ),
            };
          })(),
        }),
  };
}
export function parsePaperOperations(value: unknown): PaperOperations {
  const row = object(value, "paper operations"),
    feed = object(row.feed, "quote feed"),
    worker = object(row.worker, "operations worker");
  if (!Array.isArray(row.limitations))
    throw new ContractError("operations limitations");
  return {
    control: parseOperationsControl(row.control),
    mandate: row.mandate == null ? null : parseMandate(row.mandate),
    feed: {
      provider: text(feed.provider, "quote provider"),
      configured: bool(feed.configured, "quote feed state"),
      reason: nullableText(feed.reason, "quote feed reason"),
    },
    worker: {
      active: bool(worker.active, "operations worker state"),
      last_seen_at: nullableText(worker.last_seen_at, "worker timestamp"),
    },
    latest_observation:
      row.latest_observation == null
        ? null
        : jsonObject(row.latest_observation),
    performance: parsePaperPerformance(row.performance),
    limitations: row.limitations.map((item) =>
      text(item, "operations limitation"),
    ),
    ...(row.mandates === undefined
      ? {}
      : {
          mandates: (() => {
            if (!Array.isArray(row.mandates))
              throw new ContractError("saved mandates");
            return row.mandates.map(parseMandate);
          })(),
        }),
    ...(row.recent_actions === undefined
      ? {}
      : {
          recent_actions: rows(row.recent_actions, "recent operations actions"),
        }),
    ...(row.status === undefined
      ? {}
      : {
          status:
            typeof row.status === "string" || row.status === null
              ? row.status
              : jsonObject(row.status),
        }),
    ...(row.latest_tick === undefined
      ? {}
      : {
          latest_tick:
            row.latest_tick === null
              ? null
              : (() => {
                  const tick = object(row.latest_tick, "latest paper cycle");
                  const error =
                    tick.error == null
                      ? null
                      : object(tick.error, "paper cycle error");
                  return {
                    observed_at: utc(tick.observed_at, "paper cycle timestamp"),
                    status: text(tick.status, "paper cycle status"),
                    actions: rows(tick.actions, "paper cycle actions"),
                    error: error
                      ? {
                          code: text(error.code, "paper cycle error code"),
                          message: text(
                            error.message,
                            "paper cycle error message",
                          ),
                        }
                      : null,
                  };
                })(),
        }),
    ...(row.drawdown === undefined
      ? {}
      : {
          drawdown: (() => {
            const drawdown = object(row.drawdown, "drawdown state");
            return {
              peak_equity:
                drawdown.peak_equity == null
                  ? null
                  : decimal(drawdown.peak_equity, "peak equity"),
              tripped: bool(drawdown.tripped, "drawdown stop state"),
            };
          })(),
        }),
  };
}

export const MODE_INFO: Record<
  OperationMode,
  { name: string; description: string }
> = {
  active: {
    name: "Active",
    description:
      "New entries and position management are allowed within the selected mandate.",
  },
  exit_only: {
    name: "Exit only",
    description:
      "Cancel remaining buy orders; continue monitoring and eligible sells. Existing positions are not automatically liquidated.",
  },
  halted: {
    name: "Halted",
    description:
      "Cancel all open orders and continue monitoring. Existing positions are not automatically liquidated.",
  },
};

export type MandateFormValues = Record<
  | "name"
  | "symbols"
  | "max_symbol_weight"
  | "max_order_notional"
  | "max_quote_age_seconds"
  | "fee_bps"
  | "max_open_orders"
  | "order_ttl_seconds"
  | "max_decision_age_seconds"
  | "poll_interval_seconds"
  | "max_drawdown_amount"
  | "expires_at",
  string
>;
export const EMPTY_MANDATE: MandateFormValues = {
  name: "",
  symbols: "",
  max_symbol_weight: "",
  max_order_notional: "",
  max_quote_age_seconds: "",
  fee_bps: "",
  max_open_orders: "",
  order_ttl_seconds: "",
  max_decision_age_seconds: "",
  poll_interval_seconds: "",
  max_drawdown_amount: "",
  expires_at: "",
};
export function mandatePayload(
  values: MandateFormValues,
  now = Date.now(),
): PaperMandatePayload {
  if (Object.values(values).some((value) => !value.trim()))
    throw new Error(
      "Complete every mandate field. No risk limits are supplied automatically.",
    );
  const name = values.name.trim();
  if (name.length > 120)
    throw new Error("The mandate name must be at most 120 characters.");
  const symbols = values.symbols
    .toUpperCase()
    .split(/[\s,]+/)
    .filter(Boolean);
  if (
    !symbols.length ||
    symbols.length > 30 ||
    new Set(symbols).size !== symbols.length ||
    symbols.some((symbol) => !/^[A-Z][A-Z0-9.\-]{0,14}$/.test(symbol))
  )
    throw new Error(
      "Enter 1–30 distinct equity or ETF symbols, separated by commas.",
    );
  const dec = (
    key: keyof MandateFormValues,
    label: string,
    minimum: number,
    inclusive: boolean,
    maximum = Infinity,
  ) => {
    const raw = values[key].trim();
    const value = Number(raw);
    if (
      !/^\d+(\.\d+)?$/.test(raw) ||
      !Number.isFinite(value) ||
      (inclusive ? value < minimum : value <= minimum) ||
      value > maximum
    )
      throw new Error(`${label} is outside its allowed range.`);
    return raw;
  };
  const int = (
    key: keyof MandateFormValues,
    label: string,
    minimum: number,
    maximum: number,
  ) => {
    const raw = values[key].trim(),
      value = Number(raw);
    if (
      !/^\d+$/.test(raw) ||
      !Number.isSafeInteger(value) ||
      value < minimum ||
      value > maximum
    )
      throw new Error(
        `${label} must be a whole number from ${minimum} to ${maximum}.`,
      );
    return value;
  };
  const expiry = new Date(values.expires_at);
  if (!Number.isFinite(expiry.getTime()) || expiry.getTime() <= now)
    throw new Error("Choose a future mandate expiry.");
  return {
    name,
    allowed_symbols: symbols,
    policy: {
      max_symbol_weight: dec(
        "max_symbol_weight",
        "Maximum symbol weight",
        0,
        false,
        1,
      ),
      max_order_notional: dec(
        "max_order_notional",
        "Maximum order notional",
        0,
        false,
      ),
      max_quote_age_seconds: int(
        "max_quote_age_seconds",
        "Maximum quote age",
        1,
        60,
      ),
      fee_bps: dec("fee_bps", "Fees", 0, true, 1000),
    },
    max_open_orders: int("max_open_orders", "Maximum open orders", 1, 20),
    order_ttl_seconds: int("order_ttl_seconds", "Order lifetime", 60, 86400),
    max_decision_age_seconds: int(
      "max_decision_age_seconds",
      "Maximum decision age",
      60,
      86400,
    ),
    poll_interval_seconds: int(
      "poll_interval_seconds",
      "Poll interval",
      5,
      300,
    ),
    max_drawdown_amount: dec(
      "max_drawdown_amount",
      "Maximum drawdown amount",
      0,
      false,
    ),
    expires_at: expiry.toISOString(),
  };
}
