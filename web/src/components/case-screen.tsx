"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ChevronRight,
  GitBranch,
  Play,
  RefreshCw,
  Square,
  Terminal,
} from "lucide-react";
import {
  EVIDENCE_ARTIFACT_KINDS,
  parseCase,
  parseArtifact,
  parseCaseDetail,
  parseEvents,
  object,
  type Artifact,
  type CaseDetail,
  type Json,
  type Task,
  type ToolCall,
} from "@/lib/contracts";
import { mutate, request, message } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { dateTime, duration, isRecord, label, scalar } from "@/lib/format";
import { useEnvironment } from "./app-shell";
import { ArtifactCard, ArtifactModal } from "./artifacts";
import { InvestigationOverview } from "./investigation-overview";
import { EmptyState, ErrorNotice, JsonDetails, Loading, Status } from "./ui";

function useCaseEvents(caseId: string, onChange: () => void) {
  const [error, setError] = useState<string | null>(null),
    [updatedAt, setUpdatedAt] = useState<string | null>(null);
  useEffect(() => {
    let after = 0,
      stopped = false,
      running = false;
    const controller = new AbortController();
    async function poll() {
      if (stopped || running || document.visibilityState !== "visible") return;
      running = true;
      try {
        const data = await request(
          `/events?case_id=${encodeURIComponent(caseId)}&after=${after}`,
          parseEvents,
          { signal: controller.signal },
        );
        if (!stopped) {
          after = Math.max(after, data.cursor);
          setError(null);
          setUpdatedAt(new Date().toISOString());
          if (data.items.length) onChange();
        }
      } catch (e) {
        if (!stopped) setError(message(e));
      } finally {
        running = false;
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 3_000);
    const visible = () => void poll();
    document.addEventListener("visibilitychange", visible);
    return () => {
      stopped = true;
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [caseId, onChange]);
  return { error, updatedAt };
}

export function CaseScreen({ caseId }: { caseId: string }) {
  const detail = useResource(
    `/cases/${encodeURIComponent(caseId)}`,
    parseCaseDetail,
    15_000,
  );
  const changed = useCallback(() => {
    void detail.refresh();
  }, [detail.refresh]);
  const events = useCaseEvents(caseId, changed);
  const { capabilities, workspaces, canWrite } = useEnvironment();
  const [tab, setTab] = useState("research"),
    [selected, setSelected] = useState<Artifact | null>(null),
    [loadingSource, setLoadingSource] = useState<string | null>(null),
    [busy, setBusy] = useState<string | null>(null),
    [actionError, setActionError] = useState<string | null>(null);
  const mutationKeys = useRef<Record<string, string>>({}),
    pending = useRef(false);
  const sourceRequest = useRef<AbortController | null>(null);
  useEffect(() => () => sourceRequest.current?.abort(), [caseId]);
  function openArtifact(artifact: Artifact) {
    sourceRequest.current?.abort();
    setLoadingSource(null);
    setSelected(artifact);
  }
  async function openSource(id: string) {
    sourceRequest.current?.abort();
    const controller = new AbortController();
    sourceRequest.current = controller;
    setLoadingSource(id);
    setActionError(null);
    try {
      const artifact = await request(
        `/artifacts/${encodeURIComponent(id)}`,
        parseArtifact,
        { signal: controller.signal },
      );
      if (
        !EVIDENCE_ARTIFACT_KINDS.includes(artifact.kind) ||
        artifact.id !== id
      )
        throw new Error(
          "This reference does not resolve to the recorded evidence. Inspect the dossier for its original citation.",
        );
      if (!controller.signal.aborted) setSelected(artifact);
    } catch (e) {
      if (!controller.signal.aborted)
        setActionError(`Could not open the linked source. ${message(e)}`);
    } finally {
      if (!controller.signal.aborted) setLoadingSource(null);
    }
  }
  async function action(kind: "run" | "cancel") {
    if (!canWrite || pending.current) return;
    pending.current = true;
    setBusy(kind);
    setActionError(null);
    mutationKeys.current[kind] ||= crypto.randomUUID();
    try {
      await mutate(
        `/cases/${caseId}/${kind}`,
        kind === "run" ? { role: "coordinator" } : {},
        (value) => (kind === "cancel" ? parseCase(value) : object(value)),
        mutationKeys.current[kind],
      );
      delete mutationKeys.current[kind];
      await detail.refresh();
    } catch (e) {
      setActionError(message(e));
    } finally {
      pending.current = false;
      setBusy(null);
    }
  }
  if (!detail.data && detail.loading)
    return (
      <div className="page">
        <Loading label="Loading investigation…" />
      </div>
    );
  if (!detail.data)
    return (
      <div className="page">
        <Link className="back-link" href="/">
          <ArrowLeft size={15} />
          Research
        </Link>
        <ErrorNotice onRetry={() => void detail.refresh()}>
          {detail.error || "This investigation could not be found."}
        </ErrorNotice>
      </div>
    );
  const data = detail.data;
  const inProgress = ["running", "queued", "waiting"].includes(data.status);
  const evidence = data.artifacts.filter((a) =>
    EVIDENCE_ARTIFACT_KINDS.includes(a.kind),
  );
  return (
    <div className="page case-page">
      <Link className="back-link" href="/">
        <ArrowLeft size={14} />
        All investigations
      </Link>
      <div className="page-heading case-heading">
        <div>
          <div className="eyebrow">
            {workspaces.find((w) => w.id === data.workspace_id)?.name ||
              data.workspace_id}
          </div>
          <h1>{data.title}</h1>
          <div className="case-heading-meta">
            <Status value={data.status} />
            <span>Created {dateTime(data.created_at)}</span>
          </div>
        </div>
        <div className="heading-actions">
          <button
            className="icon-button"
            aria-label="Refresh investigation"
            onClick={() => void detail.refresh()}
          >
            <RefreshCw size={16} />
          </button>
          {canWrite &&
            (inProgress ? (
              <button
                className="button button-secondary"
                onClick={() => void action("cancel")}
                disabled={!!busy}
              >
                <Square size={14} />
                {busy === "cancel" ? "Cancelling…" : "Cancel run"}
              </button>
            ) : (
              <button
                className="button button-primary"
                onClick={() => void action("run")}
                disabled={!!busy || !capabilities?.provider.configured}
                title={
                  !capabilities?.provider.configured
                    ? "Configure a model provider before launching research."
                    : undefined
                }
              >
                <Play size={14} />
                {busy === "run"
                  ? "Starting…"
                  : data.tasks.length
                    ? "Run again"
                    : "Run investigation"}
              </button>
            ))}
        </div>
      </div>
      {detail.error && (
        <ErrorNotice stale onRetry={() => void detail.refresh()}>
          {detail.error}
        </ErrorNotice>
      )}
      {events.error && (
        <ErrorNotice>
          Activity updates are temporarily unavailable. {events.error}
        </ErrorNotice>
      )}
      {actionError && <ErrorNotice>{actionError}</ErrorNotice>}
      {data.status === "draft" && !capabilities?.provider.configured && (
        <div className="info-notice">
          Your research brief is saved. Configure a model provider in the server
          environment to launch this investigation.
        </div>
      )}
      <div
        className="case-tabs"
        role="tablist"
        aria-label="Investigation sections"
      >
        {[
          { id: "research", label: "Overview" },
          { id: "evidence", label: "Evidence", count: evidence.length },
          { id: "artifacts", label: "Artifacts", count: data.artifacts.length },
          { id: "activity", label: "Activity", count: data.tool_calls.length },
        ].map((item, index, items) => (
          <button
            key={item.id}
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`panel-${item.id}`}
            tabIndex={tab === item.id ? 0 : -1}
            className={tab === item.id ? "tab-active" : ""}
            onClick={() => setTab(item.id)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % items.length
                  : event.key === "ArrowLeft"
                    ? (index + items.length - 1) % items.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? items.length - 1
                        : null;
              if (next === null) return;
              event.preventDefault();
              setTab(items[next].id);
              event.currentTarget.parentElement
                ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
                [next]?.focus();
            }}
          >
            {item.label}
            {item.count != null && <span>{item.count}</span>}
          </button>
        ))}
        <span className="poll-status">
          <span
            className={`connection-dot ${events.error ? "connection-error" : events.updatedAt ? "connection-ok" : ""}`}
          />
          {events.error
            ? "Updates interrupted"
            : events.updatedAt
              ? "Checking for updates"
              : "Connecting"}
        </span>
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "research" && (
          <InvestigationOverview
            data={data}
            onOpen={openArtifact}
            onOpenSource={(id) => void openSource(id)}
            loadingSource={loadingSource}
            onNavigate={setTab}
          >
            <TaskList tasks={data.tasks} calls={data.tool_calls} />
          </InvestigationOverview>
        )}
        {tab === "evidence" && (
          <section className="panel">
            <div className="panel-header">
              <h2>Evidence & datasets</h2>
              <span className="muted">
                Original content and source metadata
              </span>
            </div>
            {evidence.length ? (
              <div className="artifact-list">
                {evidence.map((artifact) => (
                  <ArtifactCard
                    key={artifact.id}
                    artifact={artifact}
                    onOpen={setSelected}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No evidence recorded yet"
                description="Retrieved sources and dataset snapshots will appear here, linked to their producing tasks and input versions."
              />
            )}
          </section>
        )}
        {tab === "artifacts" && (
          <section className="panel">
            <div className="panel-header">
              <h2>All research artifacts</h2>
              <span className="muted">
                Immutable content · linked provenance
              </span>
            </div>
            {data.artifacts.length ? (
              <div className="artifact-list">
                {data.artifacts.map((artifact) => (
                  <ArtifactCard
                    key={artifact.id}
                    artifact={artifact}
                    onOpen={setSelected}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                title="The artifact record is empty"
                description="Research notes, code, datasets, experiments, reviews, and paper proposals appear here when they are actually created."
              />
            )}
          </section>
        )}
        {tab === "activity" && (
          <div className="case-layout">
            <section className="panel case-primary">
              <div className="panel-header">
                <h2>Task & tool execution</h2>
                <span className="muted">
                  {data.tool_calls.length} recorded calls
                </span>
              </div>
              {data.tasks.length ? (
                <TaskList tasks={data.tasks} calls={data.tool_calls} expanded />
              ) : (
                <EmptyState
                  title="No tasks have run"
                  description="Start the investigation to see its execution record."
                />
              )}
            </section>
            <aside className="case-aside panel">
              <div className="panel-header">
                <h2>Event history</h2>
              </div>
              <div className="panel-body">
                <EventList data={data} />
              </div>
            </aside>
          </div>
        )}
      </div>
      {selected && (
        <ArtifactModal artifact={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

export function ToolCallView({ call }: { call: ToolCall }) {
  return (
    <details className="tool-call">
      <summary>
        <Terminal size={14} />
        <span className="mono tool-name">{call.name}</span>
        <span className="tool-duration">{duration(call.duration_ms)}</span>
        <Status value={call.status} />
        <ChevronRight className="disclosure-chevron" size={14} />
      </summary>
      <div className="tool-call-body">
        <div className="tool-timestamps">
          Started {dateTime(call.started_at)}
          {call.finished_at && ` · Finished ${dateTime(call.finished_at)}`}
        </div>
        <JsonDetails title="Tool input" value={call.arguments} open />
        {call.error != null && (
          <div className="tool-error">
            <strong>Execution error</strong>
            <JsonDetails title="Error details" value={call.error} open />
          </div>
        )}
        {call.result != null ? (
          <JsonDetails title="Tool output" value={call.result} open />
        ) : (
          <p className="field-help">
            {call.status === "running"
              ? "Waiting for tool output."
              : "No output was recorded."}
          </p>
        )}
      </div>
    </details>
  );
}
function TaskList({
  tasks,
  calls,
  expanded = false,
}: {
  tasks: Task[];
  calls: ToolCall[];
  expanded?: boolean;
}) {
  return (
    <div className="task-list">
      {tasks.map((task) => {
        const taskCalls = calls.filter((call) => call.task_id === task.id);
        return (
          <details
            className={`task-item ${task.parent_id ? "task-child" : ""}`}
            key={task.id}
            open={expanded || undefined}
          >
            <summary>
              <div className="task-role-icon">
                <GitBranch size={16} />
              </div>
              <div className="task-summary">
                <strong>{label(task.role)}</strong>
                <span>{task.summary || task.instruction}</span>
              </div>
              <div className="task-summary-meta">
                <Status value={task.status} />
                <small>{taskCalls.length} tool calls</small>
              </div>
              <ChevronRight size={15} className="disclosure-chevron" />
            </summary>
            <div className="task-body">
              <div className="task-instruction">
                <div className="small-caps">ASSIGNMENT</div>
                <p className="prose preserve-lines">{task.instruction}</p>
              </div>
              {task.error != null && (
                <ErrorNotice>
                  {isRecord(task.error)
                    ? scalar(task.error.message ?? task.error)
                    : scalar(task.error)}
                </ErrorNotice>
              )}
              {task.result != null && (
                <JsonDetails title="Task result" value={task.result} />
              )}
              {taskCalls.length ? (
                taskCalls.map((call) => (
                  <ToolCallView key={call.id} call={call} />
                ))
              ) : (
                <p className="field-help">
                  No tool calls recorded for this task.
                </p>
              )}
              <div className="task-footer">
                <span>Attempt {task.attempt}</span>
                <span>Created {dateTime(task.created_at)}</span>
                <code>{task.id.slice(0, 8)}</code>
              </div>
            </div>
          </details>
        );
      })}
    </div>
  );
}
function EventList({
  data,
  compact = false,
}: {
  data: CaseDetail;
  compact?: boolean;
}) {
  const events = [...data.events]
    .sort((a, b) => b.seq - a.seq)
    .slice(0, compact ? 6 : undefined);
  if (!events.length)
    return <p className="muted text-small">No events recorded yet.</p>;
  return (
    <ol className="event-list">
      {events.map((event) => (
        <li key={event.seq}>
          <span className="event-node" />
          <div>
            <strong>{label(event.kind)}</strong>
            <time dateTime={event.created_at}>
              {dateTime(event.created_at)}
            </time>
            {!compact && (
              <JsonDetails title="Event detail" value={event.data} />
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
