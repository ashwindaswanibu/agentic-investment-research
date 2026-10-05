"use client";
import type { Json, JsonObject } from "@/lib/contracts";
import type { PaperPerformance } from "@/lib/paper-operations";
import { dateTime, isRecord, label, money, scalar } from "@/lib/format";
import { JsonDetails } from "./ui";

function decimal(value: Json | undefined): number | null {
  if ((typeof value !== "string" || !value.trim()) && typeof value !== "number")
    return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function amount(value: Json | undefined): string {
  return money(
    typeof value === "string" || typeof value === "number" ? value : null,
  );
}
function percent(value: Json | undefined): string {
  const parsed = decimal(value);
  return parsed === null
    ? "—"
    : `${(parsed * 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}
function baselineName(value: Json | undefined): string {
  if (!isRecord(value)) return "Unavailable";
  return value.kind === "account_opening"
    ? "Account opening"
    : value.kind === "previous_close"
      ? `Previous close · ${scalar(value.session)}`
      : "Unrecognized baseline";
}

export function ObservedEquityChart({ points }: { points: JsonObject[] }) {
  const samples = points.map((point) => ({
    time:
      typeof point.observed_at === "string"
        ? Date.parse(point.observed_at)
        : NaN,
    equity: point.gap_reason != null ? null : decimal(point.equity),
  }));
  const valid = samples.filter(
    (point): point is { time: number; equity: number } =>
      Number.isFinite(point.time) && point.equity !== null,
  );
  if (!valid.length) return null;
  const times = samples.map((point) => point.time).filter(Number.isFinite);
  const first = Math.min(...times),
    last = Math.max(...times);
  const lowValue = Math.min(...valid.map((point) => point.equity)),
    highValue = Math.max(...valid.map((point) => point.equity));
  const padding =
    (highValue - lowValue) * 0.15 || Math.max(Math.abs(highValue) * 0.01, 1);
  const low = lowValue - padding,
    high = highValue + padding;
  const axisFormat = new Intl.NumberFormat("en", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: Math.max(
      0,
      Math.min(8, Math.ceil(-Math.log10((high - low) / 2)) + 1),
    ),
  });
  const x = (time: number) =>
    first === last ? 355 : 60 + ((time - first) / (last - first)) * 590;
  const y = (equity: number) => 24 + ((high - equity) / (high - low)) * 154;
  const segments: { time: number; equity: number }[][] = [];
  let current: { time: number; equity: number }[] = [];
  for (const sample of samples) {
    if (sample.equity === null || !Number.isFinite(sample.time)) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push({ time: sample.time, equity: sample.equity });
  }
  if (current.length) segments.push(current);
  const gaps = samples.length - valid.length;
  return (
    <figure className="equity-chart observed-equity-chart">
      <figcaption>
        <strong>Observed paper equity</strong>
        <span>
          {samples.length} observations · {gaps} unavailable · USD
        </span>
      </figcaption>
      <svg
        viewBox="0 0 680 215"
        role="img"
        aria-label={`Recorded paper equity: ${samples.length} observations, ${gaps} unavailable. Missing valuations remain gaps.`}
      >
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
                {axisFormat.format(value)}
              </text>
            </g>
          );
        })}
        {segments.map((segment, index) => (
          <g key={index}>
            {segment.length > 1 && (
              <path
                data-equity-segment="true"
                d={segment
                  .map(
                    (point, i) =>
                      `${i ? "L" : "M"}${x(point.time).toFixed(2)},${y(point.equity).toFixed(2)}`,
                  )
                  .join(" ")}
                fill="none"
                stroke="#247769"
                strokeWidth="2.5"
                strokeLinejoin="round"
              />
            )}
            {segment.length === 1 && (
              <circle
                cx={x(segment[0].time)}
                cy={y(segment[0].equity)}
                r="3"
                fill="#247769"
              />
            )}
          </g>
        ))}
        <text x="60" y="205">
          {dateTime(new Date(first).toISOString())}
        </text>
        <text x="650" y="205" textAnchor="end">
          {dateTime(new Date(last).toISOString())}
        </text>
      </svg>
    </figure>
  );
}

export function PaperPerformancePanel({
  performance,
}: {
  performance: PaperPerformance;
}) {
  const latest = performance.latest;
  const intraday = latest && isRecord(latest.intraday) ? latest.intraday : {};
  const opening =
    latest && isRecord(latest.since_opening) ? latest.since_opening : {};
  const missing =
    latest && Array.isArray(latest.missing_symbols)
      ? latest.missing_symbols.filter(
          (value): value is string => typeof value === "string",
        )
      : [];
  const observedAt =
    latest && typeof latest.observed_at === "string"
      ? latest.observed_at
      : performance.as_of;
  const stale =
    performance.report_as_of &&
    observedAt &&
    Date.parse(performance.report_as_of) - Date.parse(observedAt) > 60_000;
  const cards = [
    { title: "Observed equity", value: amount(latest?.equity) },
    { title: "Since opening P&L", value: amount(opening.net_pnl) },
    { title: "Current-session P&L", value: amount(intraday.net_pnl) },
    { title: "Current-session return", value: percent(intraday.net_return) },
  ];
  return (
    <section className="panel operations-performance">
      <div className="panel-header">
        <h2>Observed paper performance</h2>
        <span className="muted">Recorded valuations only</span>
      </div>
      <div className="operations-panel-body">
        {performance.window && (
          <p className="field-help">
            Showing the latest {performance.window.days} days, up to{" "}
            {performance.window.max_observations.toLocaleString()} observations.
            {performance.window.truncated &&
              " Earlier observations are outside this response window."}
          </p>
        )}
        {!latest && (
          <p className="quiet-empty">
            No valuation observations have been recorded.
          </p>
        )}
        {performance.calendar_coverage?.complete === false &&
          (latest ||
            performance.equity_series.length > 0 ||
            performance.daily.length > 0) && (
            <div className="info-notice">
              Session calendar coverage is incomplete. Daily comparisons remain
              unavailable until the session calendar is verified.
            </div>
          )}
        {latest && (
          <>
            {stale && (
              <div className="info-notice">
                The latest valuation is older than this report. Values below
                describe the recorded observation, not a current market quote.
              </div>
            )}
            <div className="paper-performance-summary">
              {cards.map((card) => (
                <div key={card.title}>
                  <span>{card.title}</span>
                  <strong>{card.value}</strong>
                </div>
              ))}
            </div>
            {latest.equity == null && (
              <div className="info-notice">
                Current equity is unavailable
                {typeof latest.gap_reason === "string"
                  ? `: ${label(latest.gap_reason).toLowerCase()}`
                  : ""}
                .
                {missing.length > 0 && (
                  <> Missing marks: {missing.join(", ")}.</>
                )}{" "}
                Cash and recorded accounting changes remain separate.
              </div>
            )}
            <div className="performance-context">
              <span>
                Observed{" "}
                {dateTime(
                  typeof latest.observed_at === "string"
                    ? latest.observed_at
                    : null,
                )}
              </span>
              {performance.report_as_of && (
                <span>Report as of {dateTime(performance.report_as_of)}</span>
              )}
              <span>Session baseline: {baselineName(intraday.baseline)}</span>
            </div>
            <dl className="performance-accounting">
              <div>
                <dt>Cash</dt>
                <dd>{amount(latest.cash)}</dd>
              </div>
              <div>
                <dt>Session realized P&L</dt>
                <dd>{amount(intraday.realized_pnl_delta)}</dd>
              </div>
              <div>
                <dt>Session fees</dt>
                <dd>{amount(intraday.fees_delta)}</dd>
              </div>
              <div>
                <dt>Session fills</dt>
                <dd>
                  {typeof intraday.fills_delta === "number"
                    ? intraday.fills_delta
                    : "—"}
                </dd>
              </div>
            </dl>
          </>
        )}
        <ObservedEquityChart points={performance.equity_series} />
        {performance.daily.length > 0 && (
          <div className="table-scroll">
            <table>
              <caption>
                Daily paper accounting · latest{" "}
                {Math.min(performance.daily.length, 30)} sessions
              </caption>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Close status</th>
                  <th>Close equity</th>
                  <th>Net P&L</th>
                  <th>Return</th>
                  <th>Fees</th>
                  <th>Fills</th>
                  <th>Baseline / gap</th>
                </tr>
              </thead>
              <tbody>
                {performance.daily
                  .slice(-30)
                  .reverse()
                  .map((day, index) => (
                    <tr key={index}>
                      <td>{scalar(day.session)}</td>
                      <td>
                        {typeof day.close_status === "string"
                          ? label(day.close_status)
                          : "Unavailable"}
                      </td>
                      <td>{amount(day.close_equity)}</td>
                      <td>{amount(day.net_pnl)}</td>
                      <td>{percent(day.net_return)}</td>
                      <td>{amount(day.fees_delta)}</td>
                      <td>
                        {typeof day.fills_delta === "number"
                          ? day.fills_delta
                          : "—"}
                      </td>
                      <td>
                        {day.baseline != null
                          ? baselineName(day.baseline)
                          : typeof day.gap_reason === "string"
                            ? label(day.gap_reason)
                            : "Unavailable"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="field-help">
          Daily comparisons require consecutive qualifying session closes.
          Missing valuations stay unavailable. Fees are already included in net
          P&L; fills indicate activity, not isolated trade attribution.
        </p>
        {performance.methodology && (
          <JsonDetails
            title="Performance methodology"
            value={performance.methodology}
          />
        )}
        {(performance.latest ||
          performance.daily.length > 0 ||
          performance.equity_series.length > 0) && (
          <JsonDetails
            title="Complete observations and accounting changes"
            value={jsonPerformance(performance)}
          />
        )}
      </div>
    </section>
  );
}

function jsonPerformance(value: PaperPerformance): JsonObject {
  return {
    equity_series: value.equity_series,
    daily: value.daily,
    latest: value.latest,
    ...(value.as_of === undefined ? {} : { as_of: value.as_of }),
    ...(value.report_as_of === undefined
      ? {}
      : { report_as_of: value.report_as_of }),
    ...(value.calendar_coverage === undefined
      ? {}
      : { calendar_coverage: value.calendar_coverage }),
  };
}
