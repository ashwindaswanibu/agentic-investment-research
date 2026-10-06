"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUpRight, Clock3, Plus, RefreshCw, Target } from "lucide-react";
import { ApiError, message, mutate, request } from "@/lib/api";
import {
  EVIDENCE_ARTIFACT_KINDS,
  parseArtifact,
  type Artifact,
} from "@/lib/contracts";
import {
  localDateToISO,
  parseForecasts,
  parseResolutionContent,
  sortForecasts,
  utcDate,
  type ForecastCitation,
  type ForecastRecord,
} from "@/lib/forecasts";
import { useResource } from "@/lib/use-resource";
import { useEnvironment } from "./app-shell";
import { EmptyState, ErrorNotice, Loading } from "./ui";
import styles from "./forecasts.module.css";

type OpenSource = (id: string, sha256: string) => void;
const percent = (value: number) =>
  `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
const statusNames = {
  pending: "Pending",
  due: "Due for resolution",
  resolved: "Resolved",
  unresolvable: "Unresolvable",
  abstained: "Abstained",
};
const sourceKinds = [...EVIDENCE_ARTIFACT_KINDS, "note"];

export function ForecastPanel({
  caseId,
  artifacts,
  onOpen,
  onChanged,
}: {
  caseId: string;
  artifacts: Artifact[];
  onOpen: (artifact: Artifact) => void;
  onChanged: () => void;
}) {
  const records = useResource(
    `/cases/${encodeURIComponent(caseId)}/forecasts`,
    parseForecasts,
    15_000,
  );
  const { canWrite } = useEnvironment();
  const [registering, setRegistering] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [loadingSource, setLoadingSource] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sourceRequest = useRef<AbortController | null>(null);
  useEffect(() => () => sourceRequest.current?.abort(), []);
  async function openSource(id: string, sha256: string) {
    sourceRequest.current?.abort();
    const controller = new AbortController();
    sourceRequest.current = controller;
    setSourceError(null);
    setLoadingSource(id);
    try {
      const source = await request(
        `/artifacts/${encodeURIComponent(id)}`,
        parseArtifact,
        { signal: controller.signal },
      );
      if (source.id !== id || source.sha256 !== sha256)
        throw new Error(
          "The returned artifact does not match the recorded source ID and content hash.",
        );
      if (!controller.signal.aborted) onOpen(source);
    } catch (error) {
      if (!controller.signal.aborted)
        setSourceError(`Could not open the exact source. ${message(error)}`);
    } finally {
      if (!controller.signal.aborted) setLoadingSource(null);
    }
  }
  async function changed(text: string) {
    setNotice(text);
    await records.refresh();
    onChanged();
  }
  const items = sortForecasts(records.data ?? []);
  const due = items.filter((item) => item.assessment.status === "due").length;
  const hypotheses = artifacts.filter(
    (artifact) => artifact.kind === "hypothesis",
  );
  const inputs = artifacts.filter((artifact) =>
    sourceKinds.includes(artifact.kind),
  );
  return (
    <section className={styles.panel} aria-label="Forecast register">
      <header className={styles.heading}>
        <div>
          <h2>Forecasts & outcomes</h2>
          <p>
            Commit a binary question before its event window. Keep its
            probability, baseline, and resolution rules fixed.
          </p>
        </div>
        <div className={styles.actions}>
          <button
            className="icon-button"
            aria-label="Refresh forecasts"
            onClick={() => void records.refresh()}
          >
            <RefreshCw size={16} />
          </button>
          {canWrite && !registering && (
            <button
              className="button button-primary"
              onClick={() => {
                setRegistering(true);
                setNotice(null);
              }}
            >
              <Plus size={15} />
              Register forecast
            </button>
          )}
        </div>
      </header>
      <div className={styles.boundary}>
        Outcomes require operator review of cited evidence. Individual scores do
        not establish predictive skill or authorize trading.
      </div>
      {!canWrite && (
        <p className={styles.readOnly}>
          Read-only access · forecasts, outcomes, and source history remain
          available.
        </p>
      )}
      {notice && (
        <div className={styles.notice} role="status">
          {notice}
        </div>
      )}
      {records.error && (
        <ErrorNotice
          stale={!!records.data}
          onRetry={() => void records.refresh()}
        >
          {records.error}
        </ErrorNotice>
      )}
      {sourceError && <ErrorNotice>{sourceError}</ErrorNotice>}
      {loadingSource && (
        <p className="field-help" role="status">
          Checking the recorded source version…
        </p>
      )}
      {registering && canWrite && (
        <RegistrationForm
          caseId={caseId}
          hypotheses={hypotheses}
          sources={inputs}
          onOpenSource={(id, sha) => void openSource(id, sha)}
          onCancel={() => setRegistering(false)}
          onSaved={async () => {
            setRegistering(false);
            await changed(
              "Forecast registered. Its original probability, window, and rules are now immutable.",
            );
          }}
        />
      )}
      {records.loading && !records.data ? (
        <Loading label="Loading forecast records…" />
      ) : (
        records.data && (
          <>
            {items.length > 0 && (
              <div className={styles.summary}>
                <span>
                  <strong>{items.length}</strong> retained{" "}
                  {items.length === 1 ? "record" : "records"}
                </span>
                <span>
                  <Clock3 size={14} />
                  <strong>{due}</strong> due for operator review
                </span>
                <span>Due records appear first</span>
              </div>
            )}
            {items.length ? (
              <div className={styles.records}>
                {items.map((item) => (
                  <ForecastCard
                    key={item.forecast.id}
                    item={item}
                    artifacts={artifacts}
                    canWrite={canWrite}
                    onOpen={onOpen}
                    onOpenSource={(id, sha) => void openSource(id, sha)}
                    onRefresh={records.refresh}
                    onSaved={() =>
                      changed(
                        "Operator resolution appended. Prior judgments remain in the history.",
                      )
                    }
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No forecasts registered"
                description="Register a question against a saved hypothesis and existing source artifacts. Pending forecasts, abstentions, and unresolved outcomes stay in this record."
                icon={<Target size={25} />}
              />
            )}
          </>
        )
      )}
    </section>
  );
}

function SourceButton({
  id,
  sha256,
  children,
  onOpenSource,
}: {
  id: string;
  sha256: string;
  children: React.ReactNode;
  onOpenSource: OpenSource;
}) {
  return (
    <button
      type="button"
      className={styles.sourceButton}
      onClick={() => onOpenSource(id, sha256)}
    >
      {children}
      <ArrowUpRight size={13} />
    </button>
  );
}

function ForecastCard({
  item,
  artifacts,
  canWrite,
  onOpen,
  onOpenSource,
  onRefresh,
  onSaved,
}: {
  item: ForecastRecord;
  artifacts: Artifact[];
  canWrite: boolean;
  onOpen: (artifact: Artifact) => void;
  onOpenSource: OpenSource;
  onRefresh: () => Promise<void>;
  onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<{ previousId: string | null } | null>(
    null,
  );
  const { forecast, content, assessment, latest_resolution: latest } = item;
  const latestContent = latest ? parseResolutionContent(latest.content) : null;
  const closed = Date.parse(content.closes_at) <= Date.now();
  return (
    <article
      className={`${styles.record} ${assessment.status === "due" ? styles.due : ""}`}
      aria-label={content.question}
    >
      <div className={styles.recordTop}>
        <div className={styles.badges}>
          <span
            className={`${styles.status} ${assessment.status === "due" ? styles.dueStatus : ""}`}
          >
            {statusNames[assessment.status]}
          </span>
          {content.synthetic && (
            <span className={styles.synthetic}>Synthetic fixture</span>
          )}
          <span className={styles.immutable}>Immutable registration</span>
        </div>
        <button className="text-button" onClick={() => onOpen(forecast)}>
          Inspect record
        </button>
      </div>
      <h3>{content.question}</h3>
      <div className={styles.hypothesis}>
        Hypothesis{" "}
        <SourceButton
          id={content.hypothesis.id}
          sha256={content.hypothesis.sha256}
          onOpenSource={onOpenSource}
        >
          {content.hypothesis.title}
        </SourceButton>
      </div>
      <div className={styles.metrics}>
        <div>
          <span>Forecast · P(Yes)</span>
          <strong>
            {content.probability === null
              ? "Abstained"
              : percent(content.probability)}
          </strong>
        </div>
        <div>
          <span>Baseline · P(Yes)</span>
          <strong>{percent(content.baseline_probability)}</strong>
        </div>
        <div className={styles.window}>
          <span>Event window · UTC</span>
          <time dateTime={content.opens_at}>{utcDate(content.opens_at)}</time>
          <span>
            through{" "}
            <time dateTime={content.closes_at}>
              {utcDate(content.closes_at)}
            </time>
          </span>
        </div>
      </div>
      {content.abstention_reason && (
        <p className={styles.abstention}>
          <strong>Reason for abstaining:</strong> {content.abstention_reason}
        </p>
      )}
      {assessment.status === "due" && (
        <p className={styles.nextAction}>
          <Clock3 size={15} />
          The window has closed. Review source evidence against the saved rules,
          then record an outcome.
        </p>
      )}
      {assessment.status === "pending" && (
        <p className={styles.caption}>
          Resolution becomes available after the event window closes.
        </p>
      )}
      <details className={styles.details}>
        <summary>Registration, resolution rules & sources</summary>
        <dl className={styles.rules}>
          <div>
            <dt>Yes, if</dt>
            <dd>{content.yes_rule}</dd>
          </div>
          <div>
            <dt>No, if</dt>
            <dd>{content.no_rule}</dd>
          </div>
          <div>
            <dt>Unresolvable, if</dt>
            <dd>{content.unresolvable_rule}</dd>
          </div>
          <div>
            <dt>Designated resolution source</dt>
            <dd>{content.resolution_source}</dd>
          </div>
          <div>
            <dt>Baseline rationale</dt>
            <dd>{content.baseline_rationale}</dd>
          </div>
          <div>
            <dt>Registered by server</dt>
            <dd>
              <time dateTime={content.registered_at}>
                {utcDate(content.registered_at)}
              </time>
            </dd>
          </div>
        </dl>
        <div className={styles.sources}>
          <strong>Sources available at registration</strong>
          {content.source_refs.map((source) => (
            <div key={source.id}>
              <SourceButton
                id={source.id}
                sha256={source.sha256}
                onOpenSource={onOpenSource}
              >
                {source.title}
              </SourceButton>
              <code>{source.sha256}</code>
            </div>
          ))}
        </div>
      </details>
      {latestContent && (
        <div className={styles.outcome}>
          <span className="investigation-kicker">LATEST OPERATOR JUDGMENT</span>
          <h4>
            {latestContent.outcome === "yes"
              ? "Yes"
              : latestContent.outcome === "no"
                ? "No"
                : "Unresolvable"}
          </h4>
          <p>{latestContent.rationale}</p>
          <span className={styles.caption}>
            {utcDate(latestContent.recorded_at)}
            {latestContent.synthetic ? " · Synthetic fixture" : ""}
          </span>
          <Citations
            sources={latestContent.source_refs}
            onOpenSource={onOpenSource}
          />
        </div>
      )}
      {assessment.scored ? (
        <div className={styles.scoring} aria-label="Per-record scores">
          <div>
            <span>Forecast Brier</span>
            <strong>{assessment.brier!.toFixed(4)}</strong>
          </div>
          <div>
            <span>Baseline Brier</span>
            <strong>{assessment.baseline_brier!.toFixed(4)}</strong>
          </div>
          <div>
            <span>Improvement vs. baseline</span>
            <strong>
              {assessment.improvement! > 0 ? "+" : ""}
              {assessment.improvement!.toFixed(4)}
            </strong>
          </div>
          <p>
            Brier error: lower is better. Positive improvement means less error
            than the baseline for this record. A single outcome is not a
            calibration assessment.
          </p>
        </div>
      ) : (
        <p className={styles.caption}>
          Unscored ·{" "}
          {content.status === "abstain"
            ? "no forecast probability was committed."
            : assessment.status === "unresolvable"
              ? "the outcome could not be resolved."
              : "a Yes or No resolution is required."}
        </p>
      )}
      {item.resolutions.length > 0 && (
        <details className={styles.details}>
          <summary>
            Resolution history · {item.resolutions.length}{" "}
            {item.resolutions.length === 1 ? "entry" : "entries"}
          </summary>
          <ol className={styles.history}>
            {item.resolutions.map((artifact, index) => {
              const resolution = parseResolutionContent(artifact.content);
              return (
                <li key={artifact.id}>
                  <div className={styles.historyTitle}>
                    <strong>
                      Revision {index + 1} · {resolution.outcome}
                    </strong>
                    <span>
                      {artifact.id === latest?.id
                        ? "Current judgment"
                        : "Superseded · retained"}
                    </span>
                  </div>
                  <p>{resolution.rationale}</p>
                  <time dateTime={resolution.recorded_at}>
                    {utcDate(resolution.recorded_at)}
                  </time>
                  <Citations
                    sources={resolution.source_refs}
                    onOpenSource={onOpenSource}
                  />
                  <button
                    className="text-button"
                    onClick={() => onOpen(artifact)}
                  >
                    Inspect resolution {index + 1}
                  </button>
                </li>
              );
            })}
          </ol>
        </details>
      )}
      {canWrite && closed && !editing && (
        <div className={styles.recordActions}>
          <button
            className="button button-secondary"
            onClick={() => setEditing({ previousId: latest?.id ?? null })}
          >
            {latest ? "Append correction" : "Record resolution"}
          </button>
          <span>
            {content.status === "abstain"
              ? "An outcome can be recorded; this abstention remains unscored."
              : latest
                ? "Adds a new judgment; preserves every prior version."
                : "Requires an exact evidence excerpt and an operator rationale."}
          </span>
        </div>
      )}
      {editing && canWrite && (
        <ResolutionForm
          forecastId={forecast.id}
          previousId={editing.previousId}
          sources={artifacts.filter((a) => a.kind === "evidence")}
          onCancel={() => setEditing(null)}
          onOpenSource={onOpenSource}
          onRefresh={onRefresh}
          onSaved={async () => {
            setEditing(null);
            await onSaved();
          }}
        />
      )}
    </article>
  );
}

function Citations({
  sources,
  onOpenSource,
}: {
  sources: ForecastCitation[];
  onOpenSource: OpenSource;
}) {
  return (
    <div className={styles.citations}>
      {sources.map((source, index) => (
        <div className={styles.citation} key={`${source.artifact_id}-${index}`}>
          <SourceButton
            id={source.artifact_id}
            sha256={source.artifact_sha256}
            onOpenSource={onOpenSource}
          >
            Open exact evidence {index + 1}
          </SourceButton>
          <blockquote>{source.excerpt}</blockquote>
          <code>{source.artifact_sha256}</code>
          {source.source_path != null && (
            <span className={styles.caption}>
              JSON pointer:{" "}
              <code>{source.source_path || "(document root)"}</code>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function useSubmissionKey() {
  const previous = useRef<{ payload: string; key: string } | null>(null);
  return (body: unknown) => {
    const payload = JSON.stringify(body);
    if (previous.current?.payload !== payload)
      previous.current = { payload, key: crypto.randomUUID() };
    return previous.current.key;
  };
}

function RegistrationForm({
  caseId,
  hypotheses,
  sources,
  onCancel,
  onSaved,
  onOpenSource,
}: {
  caseId: string;
  hypotheses: Artifact[];
  sources: Artifact[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
  onOpenSource: OpenSource;
}) {
  const [status, setStatus] = useState("forecast");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [opens, setOpens] = useState("");
  const [closes, setCloses] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const submissionKey = useSubmissionKey();
  const timezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone ||
    "your browser time zone";
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError(null);
    const form = new FormData(event.currentTarget);
    const get = (name: string) => String(form.get(name) ?? "").trim();
    try {
      const hypothesis = hypotheses.find((h) => h.id === get("hypothesis_id"));
      if (!hypothesis)
        throw new Error(
          "Select an existing hypothesis for this investigation.",
        );
      if (!selectedSources.length || selectedSources.length > 10)
        throw new Error("Select between 1 and 10 existing sources.");
      const opens_at = localDateToISO(opens),
        closes_at = localDateToISO(closes);
      if (Date.parse(opens_at) <= Date.now())
        throw new Error(
          "The event window must open in the future. Registration uses the server's current time and cannot be backdated.",
        );
      if (Date.parse(closes_at) <= Date.parse(opens_at))
        throw new Error("The event window must close after it opens.");
      const body = {
        hypothesis_id: hypothesis.id,
        hypothesis_sha256: hypothesis.sha256,
        question: get("question"),
        opens_at,
        closes_at,
        yes_rule: get("yes_rule"),
        no_rule: get("no_rule"),
        unresolvable_rule: get("unresolvable_rule"),
        resolution_source: get("resolution_source"),
        status,
        probability:
          status === "forecast" ? Number(get("probability")) / 100 : null,
        abstention_reason:
          status === "abstain" ? get("abstention_reason") : null,
        baseline_probability: Number(get("baseline_probability")) / 100,
        baseline_rationale: get("baseline_rationale"),
        source_artifact_ids: selectedSources,
      };
      pending.current = true;
      setBusy(true);
      await mutate(
        `/cases/${encodeURIComponent(caseId)}/forecasts`,
        body,
        parseArtifact,
        submissionKey(body),
      );
      await onSaved();
    } catch (err) {
      setError(message(err));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      className={styles.form}
      aria-label="Register forecast"
      onSubmit={(event) => void submit(event)}
    >
      <div className={styles.formHeading}>
        <div>
          <h3>Register a prospective question</h3>
          <p>
            Registration is immutable. Save an explicit abstention when you
            cannot justify a probability.
          </p>
        </div>
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {!hypotheses.length && (
        <p className={styles.requirement}>
          A saved hypothesis artifact is required. Complete hypothesis research
          before registering a forecast.
        </p>
      )}
      {!sources.length && (
        <p className={styles.requirement}>
          At least one saved evidence, dataset, options, or note artifact is
          required.
        </p>
      )}
      <fieldset disabled={busy} className={styles.fields}>
        <label>
          Linked hypothesis
          <select name="hypothesis_id" required defaultValue="">
            <option value="" disabled>
              Select a saved hypothesis
            </option>
            {hypotheses.map((h) => (
              <option key={h.id} value={h.id}>
                {h.title} · {h.sha256.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Binary question
          <textarea
            name="question"
            required
            rows={2}
            maxLength={3000}
            placeholder="Will the defined event occur within this window?"
          />
        </label>
        <div className={styles.formGrid}>
          <label>
            Window opens · {timezone}
            <input
              type="datetime-local"
              name="opens_at"
              required
              value={opens}
              onChange={(e) => setOpens(e.target.value)}
            />
            {opens && <span>{utcDate(localDateToISO(opens))}</span>}
          </label>
          <label>
            Window closes · {timezone}
            <input
              type="datetime-local"
              name="closes_at"
              required
              value={closes}
              onChange={(e) => setCloses(e.target.value)}
            />
            {closes && <span>{utcDate(localDateToISO(closes))}</span>}
          </label>
        </div>
        <p className={styles.caption}>
          Enter local times above; saved and displayed in UTC. The server
          timestamps registration before the future event window.
        </p>
        <label>
          Commitment
          <select
            aria-label="Commitment"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="forecast">Forecast a probability</option>
            <option value="abstain">Abstain from forecasting</option>
          </select>
        </label>
        <div className={styles.formGrid}>
          {status === "forecast" ? (
            <label>
              Forecast P(Yes) · %
              <input
                name="probability"
                type="number"
                min="0"
                max="100"
                step="any"
                required
                placeholder="0–100"
              />
            </label>
          ) : (
            <label>
              Reason for abstaining
              <textarea name="abstention_reason" required rows={2} />
            </label>
          )}
          <label>
            Baseline P(Yes) · %
            <input
              name="baseline_probability"
              type="number"
              min="0"
              max="100"
              step="any"
              required
              placeholder="0–100"
            />
          </label>
        </div>
        <label>
          Baseline rationale
          <textarea
            name="baseline_rationale"
            required
            rows={2}
            placeholder="Explain the reference probability and how it was chosen."
          />
        </label>
        <div className={styles.formGrid}>
          <label>
            Yes resolution rule
            <textarea
              name="yes_rule"
              required
              rows={3}
              placeholder="An observable condition that resolves this question to Yes."
            />
          </label>
          <label>
            No resolution rule
            <textarea
              name="no_rule"
              required
              rows={3}
              placeholder="An observable condition that resolves this question to No."
            />
          </label>
        </div>
        <label>
          Unresolvable rule
          <textarea
            name="unresolvable_rule"
            required
            rows={2}
            placeholder="When missing, ambiguous, or conflicting evidence prevents resolution."
          />
        </label>
        <label>
          Designated resolution source
          <textarea
            name="resolution_source"
            required
            rows={2}
            placeholder="Name the publication, dataset, or other source to inspect after the window closes."
          />
        </label>
        <fieldset className={styles.sourcePicker}>
          <legend>Sources at registration · select 1–10</legend>
          {sources.map((source) => (
            <div key={source.id}>
              <label>
                <input
                  type="checkbox"
                  checked={selectedSources.includes(source.id)}
                  disabled={
                    !selectedSources.includes(source.id) &&
                    selectedSources.length >= 10
                  }
                  onChange={(event) =>
                    setSelectedSources((ids) =>
                      event.target.checked
                        ? [...ids, source.id]
                        : ids.filter((id) => id !== source.id),
                    )
                  }
                />
                <span>
                  {source.title}
                  <small>
                    {source.kind.replaceAll("_", " ")} ·{" "}
                    {source.sha256.slice(0, 12)}
                  </small>
                </span>
              </label>
              <SourceButton
                id={source.id}
                sha256={source.sha256}
                onOpenSource={onOpenSource}
              >
                Inspect
              </SourceButton>
            </div>
          ))}
        </fieldset>
        <div className={styles.formFooter}>
          <span>
            The original probability, baseline, sources, and rules cannot be
            edited.
          </span>
          <button
            className="button button-primary"
            type="submit"
            disabled={!hypotheses.length || !sources.length}
          >
            {busy
              ? "Registering…"
              : status === "abstain"
                ? "Register abstention"
                : "Save immutable forecast"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}

type CitationDraft = {
  key: number;
  artifactId: string;
  excerpt: string;
  pathEnabled: boolean;
  sourcePath: string;
};
function ResolutionForm({
  forecastId,
  previousId,
  sources,
  onCancel,
  onSaved,
  onOpenSource,
  onRefresh,
}: {
  forecastId: string;
  previousId: string | null;
  sources: Artifact[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
  onOpenSource: OpenSource;
  onRefresh: () => Promise<void>;
}) {
  const [citations, setCitations] = useState<CitationDraft[]>([
    { key: 0, artifactId: "", excerpt: "", pathEnabled: false, sourcePath: "" },
  ]);
  const nextKey = useRef(1);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const submissionKey = useSubmissionKey();
  function update(key: number, changes: Partial<CitationDraft>) {
    setCitations((items) =>
      items.map((item) => (item.key === key ? { ...item, ...changes } : item)),
    );
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || conflict) return;
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      const source_refs = citations.map((citation) => {
        const source = sources.find((s) => s.id === citation.artifactId);
        if (!source)
          throw new Error(
            "Select a saved evidence artifact for every citation.",
          );
        if (!citation.excerpt.trim())
          throw new Error(
            "Provide an exact source excerpt for every citation.",
          );
        return {
          artifact_id: source.id,
          artifact_sha256: source.sha256,
          excerpt: citation.excerpt,
          source_path: citation.pathEnabled ? citation.sourcePath : null,
        };
      });
      const body = {
        outcome: String(form.get("outcome")),
        rationale: String(form.get("rationale") ?? "").trim(),
        source_refs,
        previous_resolution_id: previousId,
      };
      pending.current = true;
      setBusy(true);
      await mutate(
        `/forecasts/${encodeURIComponent(forecastId)}/resolutions`,
        body,
        parseArtifact,
        submissionKey(body),
      );
      await onSaved();
    } catch (err) {
      setError(message(err));
      if (err instanceof ApiError && err.status === 409) setConflict(true);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      className={styles.form}
      aria-label={
        previousId
          ? "Append resolution correction"
          : "Record forecast resolution"
      }
      onSubmit={(event) => void submit(event)}
    >
      <div className={styles.formHeading}>
        <div>
          <h4>
            {previousId
              ? "Append a correction"
              : "Record an operator resolution"}
          </h4>
          <p>
            Apply the saved rules to the observed evidence. Source verification
            checks the citation, not the judgment.
          </p>
        </div>
        <button
          className="text-button"
          type="button"
          onClick={onCancel}
          disabled={busy}
        >
          Cancel
        </button>
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {conflict && (
        <div className={styles.requirement}>
          <p>
            The resolution history may have changed. Reload and review the
            latest judgment before trying again.
          </p>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => void onRefresh().then(onCancel)}
          >
            Reload resolution history
          </button>
        </div>
      )}
      {!sources.length && (
        <p className={styles.requirement}>
          Save a source as an evidence artifact in this investigation before
          resolving. Notes and forecasts cannot serve as resolution evidence.
        </p>
      )}
      <fieldset disabled={busy || conflict} className={styles.fields}>
        <label>
          Observed outcome
          <select name="outcome" required defaultValue="">
            <option value="" disabled>
              Select an outcome
            </option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
            <option value="unresolvable">Unresolvable</option>
          </select>
        </label>
        <label>
          Operator rationale
          <textarea
            name="rationale"
            required
            rows={3}
            placeholder="Explain how the cited evidence satisfies the saved resolution rule."
          />
        </label>
        {citations.map((citation, index) => {
          const source = sources.find((s) => s.id === citation.artifactId);
          return (
            <div className={styles.citationEditor} key={citation.key}>
              <div className={styles.citationHeading}>
                <strong>Evidence citation {index + 1}</strong>
                {citations.length > 1 && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() =>
                      setCitations((items) =>
                        items.filter((item) => item.key !== citation.key),
                      )
                    }
                  >
                    Remove citation {index + 1}
                  </button>
                )}
              </div>
              <label>
                Evidence artifact {index + 1}
                <select
                  required
                  value={citation.artifactId}
                  onChange={(e) =>
                    update(citation.key, { artifactId: e.target.value })
                  }
                >
                  <option value="" disabled>
                    Select evidence from this case
                  </option>
                  {sources.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title} · {s.sha256.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              {source && (
                <div className={styles.sourceVersion}>
                  <SourceButton
                    id={source.id}
                    sha256={source.sha256}
                    onOpenSource={onOpenSource}
                  >
                    Inspect exact evidence
                  </SourceButton>
                  <code>{source.sha256}</code>
                </div>
              )}
              <label>
                Exact excerpt {index + 1}
                <textarea
                  required
                  value={citation.excerpt}
                  rows={3}
                  onChange={(e) =>
                    update(citation.key, { excerpt: e.target.value })
                  }
                  placeholder="Copy text verbatim from the selected evidence."
                />
              </label>
              <label className={styles.checkbox}>
                <input
                  type="checkbox"
                  checked={citation.pathEnabled}
                  onChange={(e) =>
                    update(citation.key, { pathEnabled: e.target.checked })
                  }
                />
                Locate excerpt with a JSON pointer
              </label>
              {citation.pathEnabled && (
                <label>
                  JSON pointer {index + 1}
                  <input
                    value={citation.sourcePath}
                    onChange={(e) =>
                      update(citation.key, { sourcePath: e.target.value })
                    }
                    placeholder="/text (empty means document root)"
                  />
                </label>
              )}
            </div>
          );
        })}
        {citations.length < 10 && (
          <button
            className="text-button"
            type="button"
            onClick={() =>
              setCitations((items) => [
                ...items,
                {
                  key: nextKey.current++,
                  artifactId: "",
                  excerpt: "",
                  pathEnabled: false,
                  sourcePath: "",
                },
              ])
            }
          >
            + Add evidence citation
          </button>
        )}
        <div className={styles.formFooter}>
          <span>
            {previousId
              ? "This correction is pinned to the revision you opened. A newer judgment will require review."
              : "This judgment is appended permanently to the forecast history."}
          </span>
          <button
            type="submit"
            className="button button-primary"
            disabled={!sources.length}
          >
            {busy
              ? "Recording…"
              : previousId
                ? "Save correction"
                : "Save resolution"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
