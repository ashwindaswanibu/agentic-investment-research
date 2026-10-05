"use client";

import { Fragment, useId, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Clock3,
  Database,
  Search,
} from "lucide-react";
import type { Artifact, Json, JsonObject } from "@/lib/contracts";
import { isRecord, label, scalar } from "@/lib/format";
import { JsonDetails } from "./ui";
import styles from "./options-chain.module.css";

type Side = "all" | "call" | "put";
type Check =
  "all" | "missing_quote" | "missing_time" | "crossed" | "unsupported";
const PAGE_SIZE = 40;
const text = (value: Json | undefined) =>
  typeof value === "string" ? value : "";
const issueCodes = (value: Json | undefined): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
const issueMessages: Record<string, string> = {
  delayed_research_only:
    "Delayed source observations are available for research only.",
  market_coverage_unverified:
    "Market coverage has not been verified; this snapshot is not a complete-market guarantee.",
  contract_terms_unverified:
    "Deliverable, premium multiplier, settlement and exercise terms have not been verified.",
  quote_size_unit_unverified:
    "Quote sizes retain provider units; their meaning as contract liquidity has not been verified.",
  greeks_unavailable_in_sandbox:
    "The sandbox source does not provide Greeks for this snapshot.",
  crossed_quote:
    "The recorded bid exceeds the ask. These prices do not form a usable spread.",
  bid_missing: "No bid price was recorded.",
  ask_missing: "No ask price was recorded.",
  bid_nonpositive:
    "The recorded bid is zero or negative and is retained as a flagged source observation.",
  ask_nonpositive:
    "The recorded ask is zero or negative and is retained as a flagged source observation.",
  bid_size_missing: "No bid size was recorded.",
  ask_size_missing: "No ask size was recorded.",
  bid_size_zero: "The source reports zero bid size.",
  ask_size_zero: "The source reports zero ask size.",
  bid_timestamp_missing: "The source did not provide a usable bid timestamp.",
  ask_timestamp_missing: "The source did not provide a usable ask timestamp.",
  bid_timestamp_unit_unverified:
    "The bid timestamp unit could not be verified. The raw value is retained below.",
  ask_timestamp_unit_unverified:
    "The ask timestamp unit could not be verified. The raw value is retained below.",
  bid_timestamp_future:
    "The bid timestamp is later than receipt and needs investigation.",
  ask_timestamp_future:
    "The ask timestamp is later than receipt and needs investigation.",
  bid_within_nominal_delay:
    "The reported bid age is shorter than the feed's nominal delay. This does not establish a live quote.",
  ask_within_nominal_delay:
    "The reported ask age is shorter than the feed's nominal delay. This does not establish a live quote.",
  bid_older_than_delay_window:
    "The bid source time is older than the diagnostic delay window. The market session has not been checked.",
  ask_older_than_delay_window:
    "The ask source time is older than the diagnostic delay window. The market session has not been checked.",
  asynchronous_quote_sides:
    "Bid and ask observations carry different source timestamps; they are not an atomic spread.",
  contract_size_missing: "The source did not provide a contract size.",
  root_metadata_missing: "The source did not provide contract-root metadata.",
  open_interest_missing: "No open interest was recorded.",
  volume_missing: "No volume was recorded.",
  contract_deliverable_unverified:
    "The contract deliverable has not been verified. Contract size alone does not establish it.",
  nonstandard_contract_size:
    "The source reports a nonstandard contract size; contract support has not been established.",
  adjusted_root_unsupported: "This adjusted contract root is unsupported.",
  adjusted_or_nonmatching_root_unsupported:
    "This adjusted or nonmatching contract root is unsupported.",
  empty_chain: "No contracts were returned for this underlying and expiration.",
};

function issueMessage(code: string) {
  return issueMessages[code] ?? label(code);
}

function validTimestamp(value: Json | undefined): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function Timestamp({
  value,
  compact = false,
  reference,
}: {
  value: Json | undefined;
  compact?: boolean;
  reference?: Json;
}) {
  if (!validTimestamp(value))
    return <span className={styles.unavailable}>Not recorded</span>;
  const iso = new Date(value).toISOString();
  const full = `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
  return (
    <time dateTime={value} title={full}>
      {compact ? (
        <>
          {(!validTimestamp(reference) ||
            new Date(reference).toISOString().slice(0, 10) !==
              iso.slice(0, 10)) && (
            <span className={styles.sourceDate}>{iso.slice(0, 10)}</span>
          )}
          {`${iso.slice(11, 19)} UTC`}
        </>
      ) : (
        full
      )}
    </time>
  );
}

// Keep the source decimal precision; no derived price or contract-value estimate.
function price(value: Json | undefined): string {
  if (typeof value !== "string" || !/^-?\d+(?:\.\d+)?$/.test(value)) return "—";
  return value;
}

function count(value: Json | undefined): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString("en-US")
    : "—";
}

function matchesCheck(row: JsonObject, check: Check): boolean {
  const codes = issueCodes(row.issues);
  if (check === "missing_quote")
    return price(row.bid) === "—" || price(row.ask) === "—";
  if (check === "missing_time")
    return !validTimestamp(row.bid_at) || !validTimestamp(row.ask_at);
  if (check === "crossed") return codes.includes("crossed_quote");
  if (check === "unsupported") return row.contract_status === "unsupported";
  return true;
}

function Issues({ issues }: { issues: string[] }) {
  return (
    <ul className={styles.issueList}>
      {issues.map((code, index) => (
        <li key={`${code}-${index}`}>
          <strong>{label(code)}</strong>
          <p>{issueMessage(code)}</p>
        </li>
      ))}
    </ul>
  );
}

function ContractDetails({ row }: { row: JsonObject }) {
  const issues = issueCodes(row.issues);
  return (
    <div className={styles.recordDetails}>
      <div className={styles.recordDetailsHeading}>
        <h4>Contract record</h4>
        <code>{text(row.symbol) || "Symbol not recorded"}</code>
      </div>
      <dl className={styles.detailsGrid}>
        <div>
          <dt>Underlying / root</dt>
          <dd>
            {scalar(row.underlying)} / {scalar(row.root_symbol)}
          </dd>
        </div>
        <div>
          <dt>Expiration</dt>
          <dd>{scalar(row.expiration)}</dd>
        </div>
        <div>
          <dt>Reported contract size</dt>
          <dd>{count(row.contract_size)}</dd>
        </div>
        <div>
          <dt>Contract verification</dt>
          <dd>
            {text(row.contract_status)
              ? label(text(row.contract_status))
              : "Not recorded"}
          </dd>
        </div>
        <div>
          <dt>Deliverable</dt>
          <dd>
            {row.deliverable == null ? "Unverified" : scalar(row.deliverable)}
          </dd>
        </div>
        <div>
          <dt>Settlement / exercise style</dt>
          <dd>
            {row.settlement_type == null
              ? "Unverified"
              : scalar(row.settlement_type)}{" "}
            /{" "}
            {row.exercise_style == null
              ? "Unverified"
              : scalar(row.exercise_style)}
          </dd>
        </div>
        <div>
          <dt>Bid source timestamp</dt>
          <dd>
            <Timestamp value={row.bid_at} />
          </dd>
        </div>
        <div>
          <dt>Ask source timestamp</dt>
          <dd>
            <Timestamp value={row.ask_at} />
          </dd>
        </div>
        <div>
          <dt>Bid age at receipt</dt>
          <dd>
            {typeof row.bid_age_seconds === "number"
              ? `${row.bid_age_seconds.toLocaleString("en-US")} seconds`
              : "Not recorded"}
          </dd>
        </div>
        <div>
          <dt>Ask age at receipt</dt>
          <dd>
            {typeof row.ask_age_seconds === "number"
              ? `${row.ask_age_seconds.toLocaleString("en-US")} seconds`
              : "Not recorded"}
          </dd>
        </div>
      </dl>
      <p className={styles.note}>
        Bid and ask sizes are provider-reported values; their unit is
        unverified. No contract multiplier or deliverable is inferred.
      </p>
      {issues.length > 0 ? (
        <Issues issues={issues} />
      ) : (
        <p className={styles.note}>
          No row issues were recorded. This does not establish execution
          eligibility.
        </p>
      )}
      <JsonDetails title="Inspect complete contract record" value={row} />
    </div>
  );
}

export function OptionsChain({ artifact }: { artifact: Artifact }) {
  const [side, setSide] = useState<Side>("all");
  const [check, setCheck] = useState<Check>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const id = useId();
  const content = isRecord(artifact.content) ? artifact.content : {};
  const rows = useMemo(() => {
    const records = Array.isArray(content.contracts) ? content.contracts : [];
    return records
      .flatMap((row, index) => (isRecord(row) ? [{ row, index }] : []))
      .sort((a, b) => {
        const strikeA =
          price(a.row.strike) === "—" ? Infinity : Number(a.row.strike);
        const strikeB =
          price(b.row.strike) === "—" ? Infinity : Number(b.row.strike);
        return (
          strikeA - strikeB ||
          text(a.row.option_type).localeCompare(text(b.row.option_type)) ||
          a.index - b.index
        );
      });
  }, [content.contracts]);
  const filtered = useMemo(
    () =>
      rows.filter(
        ({ row }) =>
          (side === "all" || row.option_type === side) &&
          matchesCheck(row, check) &&
          (!query.trim() ||
            [row.symbol, row.strike].some((value) =>
              text(value).toLowerCase().includes(query.trim().toLowerCase()),
            )),
      ),
    [rows, side, check, query],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );
  const synthetic =
    artifact.metadata.synthetic === true || content.synthetic === true;
  const purpose =
    text(content.research_purpose) || text(artifact.metadata.research_purpose);
  const issues = issueCodes(content.issues);
  const delay =
    typeof content.delay_seconds === "number" && content.delay_seconds > 0
      ? content.delay_seconds % 60 === 0
        ? `${content.delay_seconds / 60}-minute delayed`
        : `${content.delay_seconds}-second delayed`
      : "Delay not recorded";
  const unreadableRows = Array.isArray(content.contracts)
    ? content.contracts.length - rows.length
    : 0;
  const clearFilters = () => {
    setSide("all");
    setCheck("all");
    setQuery("");
    setPage(0);
  };

  if (content.schema_version !== "options_chain.v1")
    return (
      <section className={styles.chain} aria-label="Options chain snapshot">
        <p className={styles.invalid}>
          A supported options-chain snapshot is unavailable in this record.
        </p>
        <JsonDetails
          title="Inspect saved options data"
          value={artifact.content}
          open
        />
      </section>
    );

  return (
    <section className={styles.chain} aria-label="Options chain snapshot">
      <div className={styles.sourceBar}>
        <span>
          <Database size={14} aria-hidden="true" />
          {text(content.provider)
            ? label(text(content.provider))
            : "Provider not recorded"}{" "}
          ·{" "}
          {text(content.feed) ? label(text(content.feed)) : "Feed not recorded"}
        </span>
        <span className={styles.saved}>Saved snapshot</span>
      </div>
      <div className={styles.heading}>
        <div>
          <span className={styles.eyebrow}>OPTIONS CHAIN</span>
          <h3>
            {text(content.underlying) || "Underlying not recorded"}
            <span>
              {" "}
              / {text(content.expiration) || "Expiration not recorded"}
            </span>
          </h3>
        </div>
        <div className={styles.recordCount}>
          <strong>{rows.length.toLocaleString("en-US")}</strong>
          <span>contract records</span>
        </div>
      </div>
      <div className={styles.researchNotice}>
        <Clock3 size={17} aria-hidden="true" />
        <div>
          <strong>{delay} · Research only</strong>
          <p>
            These saved quotes are not eligible for execution. A new acquisition
            creates a separate record.
          </p>
        </div>
      </div>
      {synthetic && (
        <p className={styles.synthetic}>
          <AlertTriangle size={15} aria-hidden="true" />
          <strong>Synthetic fixture</strong> — for interface testing; not
          observed market data.
        </p>
      )}
      {purpose && (
        <div className={styles.purpose}>
          <h4>Research purpose</h4>
          <p>{purpose}</p>
        </div>
      )}
      <dl className={styles.snapshotTimes}>
        <div>
          <dt>Acquisition started</dt>
          <dd>
            <Timestamp value={content.acquisition_started_at} />
          </dd>
        </div>
        <div>
          <dt>Snapshot received</dt>
          <dd>
            <Timestamp value={content.received_at} />
          </dd>
        </div>
      </dl>
      <p className={styles.timestampNote}>
        Receipt time records when the response arrived. Bid and ask source times
        are shown separately for each contract; missing times remain unknown.
        The feed's nominal delay does not guarantee quote age or freshness.
      </p>
      {issues.length > 0 && (
        <details className={styles.snapshotIssues}>
          <summary>
            <AlertTriangle size={14} aria-hidden="true" />
            Snapshot limitations<span>{issues.length}</span>
          </summary>
          <Issues issues={issues} />
        </details>
      )}
      {content.execution_eligible !== false && (
        <p className={styles.invalid}>
          This record does not confirm execution ineligibility. Treat it as
          research only.
        </p>
      )}
      {unreadableRows > 0 && (
        <p className={styles.invalid}>
          {unreadableRows} unreadable contract{" "}
          {unreadableRows === 1 ? "record is" : "records are"} retained in the
          saved data below.
        </p>
      )}
      {!Array.isArray(content.contracts) && (
        <p className={styles.invalid}>
          The saved record does not contain a readable contracts array.
        </p>
      )}

      {rows.length > 0 ? (
        <>
          <div className={styles.toolbar}>
            <div
              className={styles.sideFilters}
              role="group"
              aria-label="Option type"
            >
              {(["all", "call", "put"] as const).map((value) => (
                <button
                  type="button"
                  key={value}
                  aria-pressed={side === value}
                  onClick={() => {
                    setSide(value);
                    setPage(0);
                  }}
                >
                  {value === "all"
                    ? "All"
                    : value === "call"
                      ? "Calls"
                      : "Puts"}{" "}
                  <span>
                    {value === "all"
                      ? rows.length
                      : rows.filter(({ row }) => row.option_type === value)
                          .length}
                  </span>
                </button>
              ))}
            </div>
            <label className={styles.search}>
              <Search size={14} aria-hidden="true" />
              <span className={styles.srOnly}>Search symbol or strike</span>
              <input
                value={query}
                placeholder="Symbol or strike"
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(0);
                }}
              />
            </label>
            <label className={styles.checkFilter}>
              <span className={styles.srOnly}>Filter data issues</span>
              <select
                value={check}
                onChange={(event) => {
                  setCheck(event.target.value as Check);
                  setPage(0);
                }}
              >
                <option value="all">All data conditions</option>
                <option value="missing_quote">Missing bid or ask</option>
                <option value="missing_time">Missing source time</option>
                <option value="crossed">Crossed quotes</option>
                <option value="unsupported">Unsupported contracts</option>
              </select>
            </label>
          </div>
          <div className={styles.tableMeta}>
            <span role="status">
              {filtered.length} of {rows.length} contracts
            </span>
            <span>Ascending strike · Source prices</span>
          </div>
          {filtered.length > 0 ? (
            <div className={styles.tableContainer}>
              <table
                className={styles.table}
                aria-label="Recorded option contracts"
              >
                <thead>
                  <tr>
                    <th scope="col">Contract / strike</th>
                    <th scope="col">Bid</th>
                    <th scope="col">Ask</th>
                    <th scope="col">Open interest</th>
                    <th scope="col">Volume</th>
                    <th scope="col">Data checks</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map(({ row, index }) => {
                    const rowIssues = issueCodes(row.issues);
                    const condition =
                      row.contract_status === "unsupported"
                        ? "Unsupported"
                        : rowIssues.includes("crossed_quote")
                          ? "Crossed quote"
                          : rowIssues.some((code) =>
                                ["bid_nonpositive", "ask_nonpositive"].includes(
                                  code,
                                ),
                              )
                            ? "Nonpositive quote"
                            : price(row.bid) === "—" || price(row.ask) === "—"
                              ? "Missing quote"
                              : !validTimestamp(row.bid_at) ||
                                  !validTimestamp(row.ask_at)
                                ? "Missing source time"
                                : "";
                    const isExpanded = expanded === index;
                    const symbol = text(row.symbol) || `Contract ${index + 1}`;
                    const rowId = `${id}-contract-${index}`;
                    return (
                      <Fragment key={index}>
                        <tr
                          className={
                            isExpanded ? styles.selectedRow : undefined
                          }
                        >
                          <th scope="row" className={styles.contractCell}>
                            <div>
                              <span
                                className={
                                  row.option_type === "put"
                                    ? styles.put
                                    : styles.call
                                }
                              >
                                {text(row.option_type)
                                  ? label(text(row.option_type))
                                  : "Unknown type"}
                              </span>
                              <strong>{price(row.strike)}</strong>
                            </div>
                            <code>{symbol}</code>
                          </th>
                          {(["bid", "ask"] as const).map((quoteSide) => (
                            <td key={quoteSide} className={styles.quoteCell}>
                              <span className={styles.mobileLabel}>
                                {label(quoteSide)}
                              </span>
                              <strong
                                className={
                                  price(row[quoteSide]) === "—"
                                    ? styles.unavailable
                                    : undefined
                                }
                              >
                                {price(row[quoteSide])}
                                <span className={styles.srOnly}>
                                  {price(row[quoteSide]) === "—"
                                    ? ` ${quoteSide} unavailable`
                                    : ""}
                                </span>
                              </strong>
                              <small>
                                Size {count(row[`${quoteSide}_size`])}
                              </small>
                              <small className={styles.quoteTime}>
                                <Timestamp
                                  value={row[`${quoteSide}_at`]}
                                  compact
                                  reference={content.received_at}
                                />
                              </small>
                            </td>
                          ))}
                          <td className={styles.countCell}>
                            <span className={styles.mobileLabel}>
                              Open interest
                            </span>
                            {count(row.open_interest)}
                          </td>
                          <td className={styles.countCell}>
                            <span className={styles.mobileLabel}>Volume</span>
                            {count(row.volume)}
                          </td>
                          <td className={styles.checkCell}>
                            <span className={styles.mobileLabel}>
                              Data checks
                            </span>
                            {condition && (
                              <span className={styles.unsupported}>
                                {condition}
                              </span>
                            )}
                            <button
                              type="button"
                              aria-label={`Inspect ${symbol}`}
                              aria-expanded={isExpanded}
                              aria-controls={rowId}
                              onClick={() =>
                                setExpanded(isExpanded ? null : index)
                              }
                            >
                              <span>
                                {rowIssues.length
                                  ? `${rowIssues.length} ${rowIssues.length === 1 ? "issue" : "issues"}`
                                  : "Inspect record"}
                              </span>
                              <ChevronDown size={14} aria-hidden="true" />
                            </button>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr id={rowId} className={styles.detailRow}>
                            <td colSpan={6}>
                              <ContractDetails row={row} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={styles.empty}>
              <h4>No contracts match these filters</h4>
              <p>The full saved chain is still available.</p>
              <button type="button" onClick={clearFilters}>
                Clear filters
              </button>
            </div>
          )}
          {pageCount > 1 && (
            <nav className={styles.pagination} aria-label="Contract pages">
              <button
                type="button"
                disabled={currentPage === 0}
                onClick={() => {
                  setPage(currentPage - 1);
                  setExpanded(null);
                }}
              >
                Previous
              </button>
              <span>
                Page {currentPage + 1} of {pageCount}
              </span>
              <button
                type="button"
                disabled={currentPage + 1 === pageCount}
                onClick={() => {
                  setPage(currentPage + 1);
                  setExpanded(null);
                }}
              >
                Next
              </button>
            </nav>
          )}
          <p className={styles.note}>
            Prices and sizes are stored source observations. “—” means
            unavailable; zero is preserved. Open interest and volume have no
            per-field timestamp in this record.
          </p>
        </>
      ) : (
        <div className={styles.empty}>
          <h4>No contract records</h4>
          <p>
            This snapshot contains no readable contracts for the recorded
            underlying and expiration. No quotes have been filled in.
          </p>
        </div>
      )}
      <JsonDetails
        title="Inspect saved options data"
        value={artifact.content}
      />
    </section>
  );
}
