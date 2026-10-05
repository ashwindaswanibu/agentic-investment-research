"use client";
import { useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  ChevronRight,
  Circle,
  FolderOpen,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import { parseCases, parseCase } from "@/lib/contracts";
import { useResource } from "@/lib/use-resource";
import { message, mutate } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { useEnvironment } from "./app-shell";
import { EmptyState, ErrorNotice, Loading, Modal, Status } from "./ui";

export function ResearchScreen({ workspaceId }: { workspaceId?: string }) {
  const cases = useResource("/cases", parseCases, 8_000);
  const { capabilities, workspaces, capabilityError, canWrite } =
    useEnvironment();
  const [creating, setCreating] = useState(false),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all");
  const workspace = workspaces.find((item) => item.id === workspaceId);
  const scoped = (cases.data || []).filter(
    (item) => !workspaceId || item.workspace_id === workspaceId,
  );
  const visible = scoped.filter(
    (item) =>
      (filter === "all" ||
        (filter === "active"
          ? ["running", "queued", "waiting"].includes(item.status)
          : item.status === filter)) &&
      `${item.title} ${item.hypothesis}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const active = scoped.filter((item) =>
    ["running", "queued", "waiting"].includes(item.status),
  ).length;
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {workspace ? "SPECIALIST WORKSPACE" : "RESEARCH WORKSPACE"}
          </div>
          <h1>{workspace?.name || "Investment research"}</h1>
          <p>
            {workspace?.description ||
              "Turn a hypothesis into evidence, an experiment, and a decision."}
          </p>
        </div>
        <button
          className="button button-primary"
          onClick={() => setCreating(true)}
          disabled={!canWrite}
          title={
            !canWrite
              ? "Operator access is needed to create an investigation."
              : undefined
          }
        >
          <Plus size={16} />
          New investigation
        </button>
      </div>
      {capabilityError && <ErrorNotice>{capabilityError}</ErrorNotice>}
      {cases.error && (
        <ErrorNotice stale={!!cases.data} onRetry={() => void cases.refresh()}>
          {cases.error}
        </ErrorNotice>
      )}
      {capabilities?.read_only && (
        <div className="read-only-banner">
          You’re viewing recorded research. This deployment cannot launch agents
          or change paper decisions.
        </div>
      )}
      <div className="research-layout">
        <div className="research-primary">
          <div className="summary-strip">
            <div>
              <span>Investigations</span>
              <strong>{cases.data ? scoped.length : "—"}</strong>
            </div>
            <div>
              <span>In progress</span>
              <strong>{cases.data ? active : "—"}</strong>
            </div>
            <div>
              <span>Completed</span>
              <strong>
                {cases.data
                  ? scoped.filter((item) => item.status === "completed").length
                  : "—"}
              </strong>
            </div>
          </div>
          <section className="panel">
            <div className="panel-header">
              <h2>
                Research cases{" "}
                <span className="count">
                  {cases.data ? scoped.length : "—"}
                </span>
              </h2>
              <button
                className="icon-button"
                aria-label="Refresh investigations"
                onClick={() => void cases.refresh()}
              >
                <RefreshCw size={15} />
              </button>
            </div>
            <div className="collection-toolbar">
              <label className="search-field">
                <Search size={16} />
                <input
                  aria-label="Search investigations"
                  placeholder="Search investigations…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <select
                aria-label="Filter investigations"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">All statuses</option>
                <option value="active">In progress</option>
                <option value="completed">Completed</option>
                <option value="draft">Drafts</option>
                <option value="failed">Failed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
            {cases.loading ? (
              <Loading />
            ) : visible.length === 0 ? (
              <EmptyState
                title={
                  scoped.length
                    ? "No matching investigations"
                    : "Start with a question worth testing"
                }
                description={
                  scoped.length
                    ? "Try another search or status filter."
                    : "Describe an investment hypothesis. Specialists can gather evidence, build experiments, and challenge the result in one recorded workflow."
                }
                action={
                  !scoped.length && canWrite ? (
                    <button
                      className="button button-secondary"
                      onClick={() => setCreating(true)}
                    >
                      <Plus size={15} />
                      Create your first investigation
                    </button>
                  ) : undefined
                }
                icon={<FolderOpen size={26} strokeWidth={1.4} />}
              />
            ) : (
              <div className="case-list">
                {visible.map((item) => (
                  <Link
                    href={`/cases/${item.id}`}
                    className="case-row"
                    key={item.id}
                  >
                    <div className="case-row-top">
                      <span className="small-caps">
                        {workspaces.find((w) => w.id === item.workspace_id)
                          ?.name || item.workspace_id}
                      </span>
                      <Status value={item.status} />
                    </div>
                    <h3>
                      {item.title}
                      <ArrowRight size={17} />
                    </h3>
                    <p>{item.summary || item.hypothesis}</p>
                    <div className="case-row-footer">
                      <span>
                        {item.tool_calls_used} / {item.tool_budget} tool calls
                      </span>
                      <span>Updated {relativeTime(item.updated_at)}</span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>
        <aside className="research-aside">
          <section className="panel environment-card">
            <div className="panel-header">
              <h2>Research environment</h2>
              <span
                className={`connection-dot ${capabilities ? "connection-ok" : ""}`}
              />
            </div>
            <div className="panel-body">
              <div className="readiness-row">
                <span
                  className={
                    capabilities?.provider.configured
                      ? "readiness-good"
                      : "readiness-pending"
                  }
                >
                  {capabilities?.provider.configured ? (
                    <Check size={14} />
                  ) : (
                    <Circle size={11} />
                  )}
                </span>
                <div>
                  <strong>Model provider</strong>
                  <small>
                    {capabilities
                      ? capabilities.provider.configured
                        ? capabilities.provider.model
                        : "Connect a provider to run research"
                      : "Checking connection…"}
                  </small>
                </div>
              </div>
              <div className="readiness-row">
                <span
                  className={
                    capabilities?.worker.active
                      ? "readiness-good"
                      : "readiness-pending"
                  }
                >
                  {capabilities?.worker.active ? (
                    <Check size={14} />
                  ) : (
                    <Circle size={11} />
                  )}
                </span>
                <div>
                  <strong>Research worker</strong>
                  <small>
                    {capabilities?.worker.active
                      ? "Available for queued investigations"
                      : "No active worker reported"}
                  </small>
                </div>
              </div>
              <div className="readiness-row">
                <span
                  className={
                    capabilities?.sandbox.available
                      ? "readiness-good"
                      : "readiness-pending"
                  }
                >
                  {capabilities?.sandbox.available ? (
                    <Check size={14} />
                  ) : (
                    <Circle size={11} />
                  )}
                </span>
                <div>
                  <strong>Isolated code execution</strong>
                  <small>
                    {capabilities?.sandbox.available
                      ? "Ready for Python experiments"
                      : "Unavailable; code execution will be blocked"}
                  </small>
                </div>
              </div>
            </div>
          </section>
          <section className="research-guide">
            <div className="guide-icon">
              <Sparkles size={20} strokeWidth={1.4} />
            </div>
            <h2>A visible research process.</h2>
            <p>
              Every investigation connects its question to the work that
              follows.
            </p>
            <ol>
              <li>
                <span>01</span>
                <div>
                  <strong>Form a hypothesis</strong>
                  <small>State the mechanism and what would disprove it.</small>
                </div>
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>Gather and test</strong>
                  <small>
                    Inspect evidence, generated code, and experiment results.
                  </small>
                </div>
              </li>
              <li>
                <span>03</span>
                <div>
                  <strong>Review the conclusion</strong>
                  <small>
                    Keep objections and negative findings alongside the result.
                  </small>
                </div>
              </li>
            </ol>
            <Link href="/library">
              Explore accumulated research
              <ArrowRight size={14} />
            </Link>
          </section>
        </aside>
      </div>
      {creating && (
        <NewCaseModal
          initialWorkspace={workspaceId}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  );
}

function NewCaseModal({
  initialWorkspace,
  onClose,
}: {
  initialWorkspace?: string;
  onClose: () => void;
}) {
  const { workspaces, canWrite } = useEnvironment();
  const router = useRouter();
  const [title, setTitle] = useState(""),
    [hypothesis, setHypothesis] = useState(""),
    [workspace, setWorkspace] = useState(
      initialWorkspace || workspaces[0]?.id || "general",
    ),
    [budget, setBudget] = useState(40);
  const [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null),
    pending = useRef(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canWrite || pending.current) return;
    pending.current = true;
    setSaving(true);
    setError(null);
    key.current ||= crypto.randomUUID();
    try {
      const created = await mutate(
        "/cases",
        {
          title: title.trim(),
          hypothesis: hypothesis.trim(),
          workspace_id: workspace,
          tool_budget: budget,
        },
        parseCase,
        key.current,
      );
      router.push(`/cases/${created.id}`);
      onClose();
    } catch (e) {
      setError(message(e));
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  // A changed brief represents a new logical request after a failed attempt.
  function changed() {
    key.current = null;
  }
  return (
    <Modal title="New investigation" onClose={onClose}>
      <form className="modal-body investigation-form" onSubmit={submit}>
        <p className="muted">
          Write a research brief. You can inspect it before launching the
          agents.
        </p>
        <label htmlFor="case-title">Investigation title</label>
        <input
          id="case-title"
          autoFocus
          required
          maxLength={200}
          placeholder="A concise name for the question"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            changed();
          }}
          disabled={saving}
        />
        <label htmlFor="case-hypothesis">Hypothesis & research question</label>
        <textarea
          id="case-hypothesis"
          required
          rows={5}
          minLength={10}
          placeholder="What might be true, why might it matter, and how should the evidence be tested? Include useful sources or dataset requirements."
          value={hypothesis}
          onChange={(e) => {
            setHypothesis(e.target.value);
            changed();
          }}
          disabled={saving}
        />
        <div className="form-columns">
          <div>
            <label htmlFor="case-workspace">Specialist workspace</label>
            <select
              id="case-workspace"
              value={workspace}
              onChange={(e) => {
                setWorkspace(e.target.value);
                changed();
              }}
              disabled={saving}
            >
              {workspaces.length ? (
                workspaces.map((w) => (
                  <option value={w.id} key={w.id}>
                    {w.name}
                  </option>
                ))
              ) : (
                <option value="general">General research</option>
              )}
            </select>
          </div>
          <div>
            <label htmlFor="case-budget">Shared tool-call budget</label>
            <input
              id="case-budget"
              type="number"
              min={1}
              max={200}
              required
              value={budget}
              onChange={(e) => {
                setBudget(Number(e.target.value));
                changed();
              }}
              disabled={saving}
            />
          </div>
        </div>
        <p className="field-help">
          The budget is shared across delegated tasks. Saving a brief does not
          launch a model run.
        </p>
        {error && <ErrorNotice>{error}</ErrorNotice>}
        <div className="modal-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="button button-primary"
            disabled={saving || !canWrite}
            type="submit"
          >
            {saving ? "Creating…" : "Create investigation"}
            <ChevronRight size={15} />
          </button>
        </div>
      </form>
    </Modal>
  );
}
