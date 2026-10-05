"use client";
import { useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Check,
  Clock3,
  Pause,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { ApiError, message, mutate } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { dateTime, label } from "@/lib/format";
import { jsonObject } from "@/lib/contracts";
import {
  EMPTY_MANDATE,
  MODE_INFO,
  mandatePayload,
  parseMandate,
  parsePaperOperations,
  type MandateFormValues,
  type OperationMode,
  type PaperMandate,
} from "@/lib/paper-operations";
import { useEnvironment } from "./app-shell";
import {
  EmptyState,
  ErrorNotice,
  JsonDetails,
  Loading,
  Modal,
  StructuredValues,
} from "./ui";
import { PaperPerformancePanel } from "./paper-performance";

function utcTime(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Unavailable";
  return (
    new Intl.DateTimeFormat("en", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: "UTC",
    }).format(date) + " UTC"
  );
}

export function MandateDetails({ mandate }: { mandate: PaperMandate }) {
  const { payload: data } = mandate;
  const values = [
    ["Allowed symbols", data.allowed_symbols.join(", ")],
    ["Maximum symbol weight", `${data.policy.max_symbol_weight} of equity`],
    ["Maximum order notional", `${data.policy.max_order_notional} USD`],
    ["Maximum quote age", `${data.policy.max_quote_age_seconds} seconds`],
    ["Fees", `${data.policy.fee_bps} basis points`],
    ["Maximum open orders", String(data.max_open_orders)],
    ["Order lifetime", `${data.order_ttl_seconds} seconds`],
    ["Maximum decision age", `${data.max_decision_age_seconds} seconds`],
    ["Poll interval", `${data.poll_interval_seconds} seconds`],
    ["Drawdown threshold", `${data.max_drawdown_amount} USD`],
    ["Expires", utcTime(data.expires_at)],
  ];
  return (
    <div className="mandate-details">
      <h3>{data.name}</h3>
      <dl>
        {values.map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <JsonDetails
        title="Exact saved mandate and version hash"
        value={jsonObject(mandate)}
      />
    </div>
  );
}

export function OperationsScreen() {
  const operations = useResource(
    "/paper/operations",
    parsePaperOperations,
    10_000,
  );
  const { capabilities, canWrite, capabilityError } = useEnvironment();
  const [creating, setCreating] = useState(false);
  const [saved, setSaved] = useState<PaperMandate | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pending, setPending] = useState<OperationMode | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const pendingRef = useRef(false);
  const data = operations.data;
  const mandateMap = new Map(
    (data?.mandates || []).map((mandate) => [mandate.id, mandate]),
  );
  if (data?.mandate) mandateMap.set(data.mandate.id, data.mandate);
  if (saved) mandateMap.set(saved.id, saved);
  const choices = [...mandateMap.values()];
  const selected =
    (selectedId ? mandateMap.get(selectedId) : null) ||
    data?.mandate ||
    saved ||
    choices[0] ||
    null;
  const writable = canWrite && !!data && !operations.error;
  const expired = selected
    ? Date.parse(selected.payload.expires_at) <= Date.now()
    : false;

  async function control(mode: OperationMode) {
    if (
      !writable ||
      !data ||
      pendingRef.current ||
      (mode === "active" && (!selected || expired))
    )
      return;
    pendingRef.current = true;
    setPending(mode);
    setActionError(null);
    setNotice(null);
    try {
      await mutate(
        "/paper/operations/control",
        {
          mandate_id:
            mode === "active" ? selected!.id : data.control.mandate_id,
          mode,
          expected_version: data.control.version,
        },
        jsonObject,
        crypto.randomUUID(),
      );
      setNotice(
        `${MODE_INFO[mode].name} requested. The refreshed control record shows the saved mode; worker actions appear separately.`,
      );
      await operations.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setActionError(
          error.code === "CONTROL_CONFLICT"
            ? "Operations changed in another session. The latest state has been refreshed; review it before choosing the mode again."
            : `${message(error)} The latest operations state has been refreshed.`,
        );
        await operations.refresh();
      } else setActionError(message(error));
    } finally {
      pendingRef.current = false;
      setPending(null);
    }
  }

  return (
    <div className="page operations-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">BOUNDED PAPER EXECUTION</div>
          <h1>Paper operations</h1>
          <p>
            Set explicit operating limits, inspect the worker, and follow
            recorded paper actions.
          </p>
        </div>
        <div className="page-heading-actions">
          <Link href="/portfolio" className="button button-secondary">
            Portfolio
            <ArrowRight size={14} />
          </Link>
          <button
            className="button button-secondary"
            onClick={() => void operations.refresh()}
          >
            <RefreshCw size={15} />
            Refresh
          </button>
        </div>
      </div>
      <div className="paper-notice">
        <ShieldCheck size={18} />
        <div>
          <strong>Paper execution only</strong>
          <span>
            Mandates govern the paper worker. Saving a mandate does not activate
            it; mode changes do not liquidate positions.
          </span>
        </div>
      </div>
      {capabilities?.read_only && (
        <div className="read-only-banner">
          Read-only view. Mandates and operating modes cannot be changed here.
        </div>
      )}
      {capabilityError && <ErrorNotice>{capabilityError}</ErrorNotice>}
      {operations.error && (
        <ErrorNotice stale={!!data} onRetry={() => void operations.refresh()}>
          {operations.error}
        </ErrorNotice>
      )}
      {actionError && <ErrorNotice>{actionError}</ErrorNotice>}
      {data?.drawdown?.tripped && (
        <div className="info-notice">
          The drawdown stop is latched. Review and save a new mandate before
          resuming new entries. Existing positions are not automatically
          liquidated.
        </div>
      )}
      {notice && (
        <div className="info-notice" role="status">
          {notice}
        </div>
      )}
      {operations.loading ? (
        <Loading label="Loading paper operations…" />
      ) : (
        data && (
          <>
            <div className="operations-layout">
              <section className="panel operation-control-panel">
                <div className="panel-header">
                  <h2>Operating mode</h2>
                  <span className="muted">
                    Control version {data.control.version}
                  </span>
                </div>
                <div className="operations-panel-body">
                  <div
                    className={`operation-mode operation-mode-${data.control.mode}`}
                  >
                    <span className="small-caps">Recorded mode</span>
                    <h3>{MODE_INFO[data.control.mode].name}</h3>
                    <p>{MODE_INFO[data.control.mode].description}</p>
                  </div>
                  <div className="operation-actions">
                    <div>
                      <button
                        className="button button-primary"
                        onClick={() => void control("active")}
                        disabled={
                          !writable ||
                          !!pending ||
                          !selected ||
                          expired ||
                          (data.drawdown?.tripped === true &&
                            data.control.mandate_id === selected?.id) ||
                          (data.control.mode === "active" &&
                            data.control.mandate_id === selected.id)
                        }
                      >
                        <Play size={14} />
                        {pending === "active"
                          ? "Activating…"
                          : "Activate selected mandate"}
                      </button>
                      <p>
                        Allow new entries and management within the exact saved
                        limits shown below.
                      </p>
                    </div>
                    <div>
                      <button
                        className="button button-secondary"
                        onClick={() => void control("exit_only")}
                        disabled={
                          !writable ||
                          !!pending ||
                          !data.control.mandate_id ||
                          data.control.mode === "exit_only"
                        }
                      >
                        <ArrowRight size={14} />
                        {pending === "exit_only"
                          ? "Updating…"
                          : "Set exit only"}
                      </button>
                      <p>
                        Cancel remaining buys; continue monitoring and eligible
                        sells. No automatic liquidation.
                      </p>
                    </div>
                    <div>
                      <button
                        className="button button-secondary"
                        onClick={() => void control("halted")}
                        disabled={
                          !writable ||
                          !!pending ||
                          data.control.mode === "halted"
                        }
                      >
                        <Pause size={14} />
                        {pending === "halted" ? "Halting…" : "Halt orders"}
                      </button>
                      <p>
                        Cancel all open orders; continue monitoring. Positions
                        remain held.
                      </p>
                    </div>
                  </div>
                  <p className="field-help">
                    A configured mode is distinct from an active worker or a
                    completed fill. Actions depend on current quotes and the
                    backend admission checks.
                  </p>
                </div>
              </section>
              <section className="panel operations-readiness">
                <div className="panel-header">
                  <h2>Operational readiness</h2>
                </div>
                <div className="operations-panel-body">
                  <dl className="operations-status-list">
                    <div>
                      <dt>Quote feed</dt>
                      <dd>
                        {data.feed.provider}
                        <span>
                          {data.feed.configured ? "Configured" : "Unavailable"}
                        </span>
                        {data.feed.reason && <small>{data.feed.reason}</small>}
                      </dd>
                    </div>
                    <div>
                      <dt>Paper worker</dt>
                      <dd>
                        {data.worker.active
                          ? "Heartbeat active"
                          : "No active heartbeat"}
                        <small>
                          {data.worker.last_seen_at
                            ? `Last seen ${dateTime(data.worker.last_seen_at)}`
                            : "No heartbeat recorded"}
                        </small>
                      </dd>
                    </div>
                    <div>
                      <dt>Controlled mandate</dt>
                      <dd>
                        {data.mandate?.payload.name ||
                          (data.control.mandate_id
                            ? "Saved mandate unavailable"
                            : "No mandate selected")}
                      </dd>
                    </div>
                  </dl>
                  {data.status &&
                    (typeof data.status === "string" ? (
                      <p className="prose">{data.status}</p>
                    ) : (
                      <StructuredValues value={data.status} />
                    ))}
                  {data.latest_observation ? (
                    <JsonDetails
                      title="Latest worker observation"
                      value={data.latest_observation}
                    />
                  ) : (
                    <p className="quiet-empty">
                      No worker observation has been recorded.
                    </p>
                  )}
                </div>
              </section>
            </div>
            <section className="panel mandate-panel">
              <div className="panel-header">
                <h2>Saved mandate</h2>
                <button
                  className="button button-secondary button-small"
                  disabled={!canWrite}
                  onClick={() => setCreating(true)}
                >
                  <Plus size={14} />
                  New mandate
                </button>
              </div>
              <div className="operations-panel-body">
                {choices.length > 0 && (
                  <label className="mandate-selector">
                    Review a saved version
                    <select
                      aria-label="Saved mandate version"
                      value={selected?.id || ""}
                      onChange={(event) => {
                        setSelectedId(event.target.value);
                        setNotice(null);
                      }}
                    >
                      {choices.map((mandate) => (
                        <option key={mandate.id} value={mandate.id}>
                          {mandate.payload.name} · {mandate.sha256.slice(0, 8)}
                          {data.control.mandate_id === mandate.id
                            ? " · controlled"
                            : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {selected ? (
                  <>
                    {data.control.mandate_id !== selected.id && (
                      <div className="info-notice">
                        This saved version is not the controlled mandate. Review
                        its limits, then use Activate selected mandate to apply
                        it.
                      </div>
                    )}
                    {expired && (
                      <div className="info-notice">
                        This mandate has expired. Save a new version to activate
                        future operations.
                      </div>
                    )}
                    <MandateDetails mandate={selected} />
                  </>
                ) : (
                  <EmptyState
                    title="No mandate has been saved"
                    description="Choose every limit explicitly. Save the complete mandate, review its version, then activate it separately."
                    icon={<ShieldCheck size={25} strokeWidth={1.4} />}
                  />
                )}
              </div>
            </section>
            <PaperPerformancePanel performance={data.performance} />
            <section className="panel">
              <div className="panel-header">
                <h2>Latest worker cycle</h2>
                <span className="muted">Persisted actions and outcomes</span>
              </div>
              <div className="operations-panel-body">
                {data.latest_tick ? (
                  <>
                    <div className="paper-cycle-heading">
                      <strong>{label(data.latest_tick.status)}</strong>
                      <span>{dateTime(data.latest_tick.observed_at)}</span>
                    </div>
                    {data.latest_tick.error && (
                      <ErrorNotice>
                        {data.latest_tick.error.message}{" "}
                        <span className="mono">
                          ({data.latest_tick.error.code})
                        </span>
                      </ErrorNotice>
                    )}
                    {data.latest_tick.actions.length ? (
                      data.latest_tick.actions.map((action, index) => (
                        <div className="paper-action-record" key={index}>
                          <strong>
                            {typeof action.action === "string"
                              ? label(action.action)
                              : "Recorded action"}
                          </strong>
                          {typeof action.message === "string" && (
                            <p className="prose">{action.message}</p>
                          )}
                          <StructuredValues
                            value={Object.fromEntries(
                              Object.entries(action).filter(
                                ([key]) => !["action", "message"].includes(key),
                              ),
                            )}
                            max={6}
                          />
                          <JsonDetails title="Action details" value={action} />
                        </div>
                      ))
                    ) : (
                      <p className="quiet-empty">
                        No actions were recorded in this cycle.
                      </p>
                    )}
                  </>
                ) : (
                  <p className="quiet-empty">
                    No worker cycle has been recorded.
                  </p>
                )}
              </div>
            </section>
            {data.limitations.length > 0 && (
              <details className="operations-limitations">
                <summary>Current operating boundaries</summary>
                <ul>
                  {data.limitations.map((limitation, index) => (
                    <li key={index}>{limitation}</li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )
      )}
      {creating && (
        <NewMandateModal
          onClose={() => setCreating(false)}
          onSaved={(mandate) => {
            setSaved(mandate);
            setSelectedId(mandate.id);
            setCreating(false);
            setNotice(
              "Mandate saved as an immutable version. Review the limits before activating it.",
            );
            void operations.refresh();
          }}
        />
      )}
    </div>
  );
}

const mandateFields: {
  key: keyof MandateFormValues;
  label: string;
  hint: string;
  inputMode?: "decimal" | "numeric";
  type?: string;
}[] = [
  {
    key: "name",
    label: "Mandate name",
    hint: "A name for this immutable version.",
  },
  {
    key: "symbols",
    label: "Allowed symbols",
    hint: "1–30 distinct equity or ETF symbols, separated by commas.",
  },
  {
    key: "max_symbol_weight",
    label: "Maximum symbol weight (fraction)",
    hint: "Greater than 0 and at most 1; 1 represents 100% of equity.",
    inputMode: "decimal",
  },
  {
    key: "max_order_notional",
    label: "Maximum order notional (USD)",
    hint: "Positive dollar limit for each order.",
    inputMode: "decimal",
  },
  {
    key: "max_quote_age_seconds",
    label: "Maximum quote age (seconds)",
    hint: "Whole seconds from 1 to 60.",
    inputMode: "numeric",
  },
  {
    key: "fee_bps",
    label: "Fees (basis points)",
    hint: "0–1,000 basis points; 100 basis points equals 1%.",
    inputMode: "decimal",
  },
  {
    key: "max_open_orders",
    label: "Maximum open orders",
    hint: "A whole number from 1 to 20.",
    inputMode: "numeric",
  },
  {
    key: "order_ttl_seconds",
    label: "Order lifetime (seconds)",
    hint: "Whole seconds from 60 to 86,400.",
    inputMode: "numeric",
  },
  {
    key: "max_decision_age_seconds",
    label: "Maximum decision age (seconds)",
    hint: "Whole seconds from 60 to 86,400.",
    inputMode: "numeric",
  },
  {
    key: "poll_interval_seconds",
    label: "Poll interval (seconds)",
    hint: "Whole seconds from 5 to 300.",
    inputMode: "numeric",
  },
  {
    key: "max_drawdown_amount",
    label: "Drawdown threshold (USD)",
    hint: "A positive amount for the observed drawdown control.",
    inputMode: "decimal",
  },
  {
    key: "expires_at",
    label: "Mandate expiry (local time)",
    hint: "Choose a future date and time. It will be saved in UTC.",
    type: "datetime-local",
  },
];

function NewMandateModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (mandate: PaperMandate) => void;
}) {
  const { canWrite } = useEnvironment();
  const [values, setValues] = useState<MandateFormValues>({ ...EMPTY_MANDATE });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const attempt = useRef<{ signature: string; key: string } | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || busy.current) return;
    setError(null);
    try {
      const payload = mandatePayload(values);
      const signature = JSON.stringify(payload);
      if (attempt.current?.signature !== signature)
        attempt.current = { signature, key: crypto.randomUUID() };
      busy.current = true;
      setSaving(true);
      const mandate = await mutate(
        "/paper/mandates",
        payload,
        parseMandate,
        attempt.current.key,
      );
      onSaved(mandate);
    } catch (failure) {
      setError(message(failure));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }
  return (
    <Modal title="Save a paper mandate" onClose={onClose} wide>
      <form className="modal-body mandate-form" onSubmit={submit}>
        <div className="quality-scope">
          <strong>All limits are explicit</strong>
          <p>
            Saving creates an immutable mandate. Activation is a separate action
            after you review the saved version.
          </p>
        </div>
        {error && <ErrorNotice>{error}</ErrorNotice>}
        <div className="mandate-form-grid">
          {mandateFields.map((field) => (
            <div key={field.key}>
              <label htmlFor={`mandate-${field.key}`}>{field.label}</label>
              <input
                id={`mandate-${field.key}`}
                type={field.type || "text"}
                inputMode={field.inputMode}
                value={values[field.key]}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
                required
                disabled={!canWrite || saving}
                autoComplete="off"
                aria-describedby={`mandate-help-${field.key}`}
              />
              <p className="field-help" id={`mandate-help-${field.key}`}>
                {field.hint}
              </p>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="button button-primary"
            disabled={!canWrite || saving}
          >
            {saving ? <Clock3 size={15} /> : <Check size={15} />}
            {saving ? "Saving…" : "Save inactive mandate"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
