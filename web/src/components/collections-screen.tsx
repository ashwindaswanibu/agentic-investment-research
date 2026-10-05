"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Filter,
  FlaskConical,
  RefreshCw,
  Search,
} from "lucide-react";
import { ARTIFACT_KINDS, parseArtifacts, type Artifact } from "@/lib/contracts";
import { useResource } from "@/lib/use-resource";
import { dateTime, isRecord, label } from "@/lib/format";
import { ArtifactCard, ArtifactModal, metricValue } from "./artifacts";
import { EmptyState, ErrorNotice, Loading, Status } from "./ui";

export function ExperimentsScreen() {
  const results = useResource("/experiments", parseArtifacts, 10_000);
  const [selected, setSelected] = useState<Artifact | null>(null);
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">MEASURED RESEARCH</div>
          <h1>Experiments</h1>
          <p>
            Inspect what was tested, how it performed, and which evidence
            supports it.
          </p>
        </div>
        <button
          className="button button-secondary"
          onClick={() => void results.refresh()}
        >
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>
      {results.error && (
        <ErrorNotice
          stale={!!results.data}
          onRetry={() => void results.refresh()}
        >
          {results.error}
        </ErrorNotice>
      )}
      <section className="panel">
        <div className="panel-header">
          <h2>
            Experiment register{" "}
            <span className="count">{results.data?.length ?? "—"}</span>
          </h2>
          <span className="muted">
            Results remain tied to their input versions
          </span>
        </div>
        {results.loading ? (
          <Loading label="Loading experiments…" />
        ) : !results.data?.length ? (
          <EmptyState
            title="No experiments have been recorded"
            description="Create an investigation to develop and test a hypothesis. Results appear here when an experiment has actually run."
            icon={<FlaskConical size={26} strokeWidth={1.4} />}
            action={
              <Link className="button button-secondary" href="/">
                Go to research
                <ArrowRight size={14} />
              </Link>
            }
          />
        ) : (
          <div className="experiment-list">
            {results.data.map((artifact) => {
              const content = isRecord(artifact.content)
                  ? artifact.content
                  : {},
                metrics = isRecord(content.metrics) ? content.metrics : {};
              return (
                <button
                  className="experiment-row"
                  key={artifact.id}
                  onClick={() => setSelected(artifact)}
                >
                  <div className="experiment-row-title">
                    <span className="artifact-icon artifact-icon-experiment">
                      <FlaskConical size={19} />
                    </span>
                    <div>
                      <h3>{artifact.title}</h3>
                      <span className="text-small muted">
                        {dateTime(artifact.created_at)} ·{" "}
                        <span className="mono">
                          {artifact.sha256.slice(0, 8)}
                        </span>
                      </span>
                    </div>
                  </div>
                  <div className="experiment-row-metrics">
                    {[
                      "net_return",
                      "max_drawdown",
                      "sharpe",
                      "geometrically_linked_fold_return",
                    ]
                      .filter((key) => key in metrics)
                      .slice(0, 3)
                      .map((key) => (
                        <div key={key}>
                          <span>{label(key)}</span>
                          <strong>{metricValue(key, metrics[key])}</strong>
                        </div>
                      ))}
                  </div>
                  {typeof content.status === "string" && (
                    <Status value={content.status} />
                  )}
                  <ArrowRight size={16} />
                </button>
              );
            })}
          </div>
        )}
      </section>
      <p className="page-note">
        Historical simulations and paper decisions are distinct records. A
        positive backtest alone does not establish a useful strategy.
      </p>
      {selected && (
        <ArtifactModal artifact={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

export function LibraryScreen() {
  const [query, setQuery] = useState(""),
    [debounced, setDebounced] = useState(""),
    [kind, setKind] = useState("all"),
    [selected, setSelected] = useState<Artifact | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 350);
    return () => clearTimeout(timer);
  }, [query]);
  const searching = debounced.length >= 2;
  const results = useResource(
    searching ? `/library?q=${encodeURIComponent(debounced)}` : "/artifacts",
    parseArtifacts,
  );
  const items = (results.data || []).filter(
    (artifact) => kind === "all" || artifact.kind === kind,
  );
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">ACCUMULATED KNOWLEDGE</div>
          <h1>Research library</h1>
          <p>
            Find prior evidence, reusable code, and experiments—including ideas
            that did not hold up.
          </p>
        </div>
        <span className="library-mark">
          <BookOpen size={28} strokeWidth={1.25} />
        </span>
      </div>
      <div className="library-search">
        <Search size={21} />
        <input
          aria-label="Search research library"
          placeholder="Search a question, method, or prior finding…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <kbd>RESEARCH RETRIEVAL</kbd>
      </div>
      {results.error && (
        <ErrorNotice onRetry={() => void results.refresh()}>
          {results.error}
        </ErrorNotice>
      )}
      <section className="panel">
        <div className="panel-header">
          <h2>
            {searching ? "Search results" : "Recorded artifacts"}
            <span className="count">{results.data ? items.length : "—"}</span>
          </h2>
          <label className="kind-filter">
            <Filter size={14} />
            <select
              aria-label="Artifact type"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {[
                "all",
                ...new Set([
                  ...ARTIFACT_KINDS,
                  ...(results.data || []).map((a) => a.kind),
                ]),
              ].map((value) => (
                <option value={value} key={value}>
                  {value === "all" ? "All types" : label(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {results.loading ? (
          <Loading
            label={
              searching ? "Searching recorded research…" : "Loading library…"
            }
          />
        ) : !items.length ? (
          <EmptyState
            title={
              searching
                ? "No matching research"
                : "Your research library starts here"
            }
            description={
              searching
                ? "Try a broader query or another artifact type. Only recorded artifacts are searched."
                : "Evidence, strategy code, and experiment findings become available as investigations produce them."
            }
            icon={<BookOpen size={26} strokeWidth={1.4} />}
          />
        ) : (
          <div className="artifact-list">
            {items.map((artifact) => (
              <ArtifactCard
                key={artifact.id}
                artifact={artifact}
                onOpen={setSelected}
              />
            ))}
          </div>
        )}
      </section>
      {selected && (
        <ArtifactModal artifact={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
