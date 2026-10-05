"use client";
import type { Json } from "@/lib/contracts";
import { isRecord, label, scalar } from "@/lib/format";
import { JsonDetails } from "./ui";

function percent(value: Json | undefined) {
  const number =
    typeof value === "string" || typeof value === "number"
      ? Number(value)
      : NaN;
  return Number.isFinite(number)
    ? `${(number * 100).toFixed(2)}%`
    : "Not recorded";
}

export function StrategyAssessment({ value }: { value: Json | undefined }) {
  if (!isRecord(value) || value.schema_version !== "strategy-assessment.v1")
    return null;
  const periods = Array.isArray(value.periods)
    ? value.periods.filter(isRecord)
    : [];
  const checks = Array.isArray(value.checks)
    ? value.checks.filter(isRecord)
    : [];
  return (
    <section className="strategy-assessment" aria-label="Strategy assessment">
      <div className="assessment-heading">
        <span className="small-caps">Automatic strategy assessment</span>
        <span className="assessment-unproven">Edge unestablished</span>
      </div>
      <h3>{scalar(value.headline)}</h3>
      <p className="field-help">
        {value.basis === "reset_walk_forward_folds"
          ? "Portfolios reset between test folds. Linked returns do not describe a continuously traded account."
          : "A historical result under the recorded assumptions. Profitability, baseline outperformance and predictive edge are different questions."}
      </p>
      {value.synthetic_data === true && (
        <p className="assessment-warning">
          Synthetic prices · software verification only
        </p>
      )}
      {periods.map((period, i) => {
        const baselines = isRecord(period.baselines) ? period.baselines : {};
        return (
          <div className="assessment-period" key={i}>
            <h4>
              {periods.length > 1 ? `Fold ${i + 1} · ` : ""}
              {scalar(period.start_session)} → {scalar(period.end_session)}
            </h4>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label={`Period ${i + 1} comparison`}
            >
              <table>
                <thead>
                  <tr>
                    <th>Policy</th>
                    <th>Return</th>
                    <th>Strategy difference</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Strategy</td>
                    <td>{percent(period.net_return)}</td>
                    <td>—</td>
                  </tr>
                  {(["cash", "buy_hold"] as const).map((name) => {
                    const baseline = baselines[name];
                    return (
                      <tr key={name}>
                        <td>
                          {name === "cash"
                            ? "Cash (recorded assumption)"
                            : "Buy and hold"}
                        </td>
                        <td>
                          {isRecord(baseline)
                            ? percent(baseline.net_return)
                            : "Missing"}
                        </td>
                        <td>
                          {isRecord(baseline)
                            ? percent(baseline.difference).replace("%", " pp")
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="assessment-context">
              {scalar(period.sessions)} sessions · {scalar(period.fill_count)}{" "}
              fills · {percent(period.max_drawdown)} maximum drawdown
            </p>
            <p className="assessment-context">
              Invested on {scalar(period.invested_sessions)} sessions. Average
              allocation at the close: {percent(period.mean_close_exposure)}.
              This comparison does not match market risk.
            </p>
          </div>
        );
      })}
      <details
        className="assessment-checks"
        open={value.status === "unavailable" || undefined}
      >
        <summary>
          Evidence and validation gaps ·{" "}
          {
            checks.filter((c) =>
              ["missing", "failed"].includes(String(c.status)),
            ).length
          }{" "}
          unresolved checks
        </summary>
        <ul>
          {checks.map((check, i) => (
            <li key={i}>
              <span>
                {label(scalar(check.code))} · {label(scalar(check.status))}
              </span>
              <p>{scalar(check.message)}</p>
            </li>
          ))}
        </ul>
      </details>
      <p className="field-help">
        Computed from retained records. This report does not grade originality,
        prove alpha or authorize trading.
      </p>
      <JsonDetails title="Assessment method and exact inputs" value={value} />
    </section>
  );
}
