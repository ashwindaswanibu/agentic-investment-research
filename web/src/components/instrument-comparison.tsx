"use client";

import { useState } from "react";
import { AlertTriangle, Clock3, Columns3 } from "lucide-react";
import type { Artifact, Json, JsonObject } from "@/lib/contracts";
import { isRecord, label } from "@/lib/format";
import { JsonDetails } from "./ui";
import styles from "./instrument-comparison.module.css";

const record = (value: Json | undefined): JsonObject =>
  isRecord(value) ? value : {};
const records = (value: Json | undefined): JsonObject[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: Json | undefined, fallback = "Not recorded") =>
  typeof value === "string" && value.trim() ? value : fallback;
const texts = (value: Json | undefined): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
const numeric = (value: Json | undefined): number | null =>
  typeof value === "string" &&
  /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?$/.test(value) &&
  Number.isFinite(Number(value))
    ? Number(value)
    : null;
const computed = (value: Json | undefined): JsonObject | null =>
  isRecord(value) && value.status === "computed" ? value : null;

function timestamp(value: Json | undefined) {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value)))
    return "Not recorded";
  return `${new Date(value).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

function quantity(result: JsonObject | null) {
  if (
    !result ||
    typeof result.quantity !== "number" ||
    !Number.isSafeInteger(result.quantity) ||
    result.quantity < 0
  )
    return "—";
  if (result.quantity_unit === "cash") return "Cash reserve";
  const unit =
    result.quantity_unit === "shares"
      ? "shares"
      : result.quantity_unit === "contracts"
        ? "contracts"
        : result.quantity_unit === "spreads"
          ? "spreads"
          : "units";
  return `${result.quantity.toLocaleString("en-US")} ${result.quantity === 1 ? unit.slice(0, -1) : unit}`;
}

function sizingBasis(candidate: JsonObject) {
  if (candidate.sizing_basis === "requested_quantity")
    return "Investigator-specified";
  if (candidate.sizing_basis === "maximum_affordable")
    return "Maximum affordable";
  if (candidate.sizing_basis === "cash") return "Full capital held as cash";
  return "Sizing basis not recorded";
}

function percent(value: Json | undefined) {
  const number = numeric(value);
  return number === null
    ? "—"
    : `${(number * 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
}

function Issues({ value }: { value: Json | undefined }) {
  const issues = records(value);
  return issues.length > 0 ? (
    <ul className={styles.issues}>
      {issues.map((issue, index) => (
        <li key={index}>
          <strong>
            {text(issue.code, "Recorded issue").replaceAll("_", " ")}
          </strong>
          <span>{text(issue.message)}</span>
        </li>
      ))}
    </ul>
  ) : null;
}

function Binding({ title, value }: { title: string; value: Json | undefined }) {
  const binding = record(value);
  return (
    <div className={styles.binding}>
      <h5>{title}</h5>
      {typeof binding.title === "string" && <p>{binding.title}</p>}
      <dl>
        <div>
          <dt>Artifact</dt>
          <dd>
            <code>{text(binding.id ?? binding.artifact_id)}</code>
          </dd>
        </div>
        <div>
          <dt>SHA-256</dt>
          <dd>
            <code>{text(binding.sha256 ?? binding.artifact_sha256)}</code>
          </dd>
        </div>
      </dl>
    </div>
  );
}

export function InstrumentComparison({ artifact }: { artifact: Artifact }) {
  const [scenarioMode, setScenarioMode] = useState<"base" | "adverse">("base");
  const content = record(artifact.content);
  const assumptions = record(content.assumptions);
  const candidates = records(content.candidates);
  const scenarios = records(assumptions.scenarios);
  const hypothesis = record(content.hypothesis);
  const timing = record(content.timing);
  const stock = record(timing.stock_reference);
  const bindings = record(content.source_bindings);
  const probabilitiesSupplied =
    scenarios.length > 0 &&
    scenarios.every((scenario) => {
      const probability = numeric(scenario.probability);
      return probability !== null && probability >= 0 && probability <= 1;
    });
  const weighted =
    content.probability_basis === "supplied_scenario_assumptions" &&
    probabilitiesSupplied &&
    Math.abs(
      scenarios.reduce(
        (sum, scenario) => sum + (numeric(scenario.probability) ?? 0),
        0,
      ) - 1,
    ) < 1e-12;
  const synthetic =
    content.synthetic === true || artifact.metadata.synthetic === true;
  const amount = (value: Json | undefined) => {
    const number = numeric(value);
    return number === null
      ? "—"
      : new Intl.NumberFormat("en-US", {
          ...(content.currency === "USD"
            ? { style: "currency", currency: "USD" }
            : {}),
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(number);
  };
  const signClass = (value: Json | undefined) =>
    (numeric(value) ?? 0) < 0 ? styles.negative : undefined;
  const candidateName = (candidate: JsonObject) =>
    text(
      candidate.label,
      label(text(candidate.instrument, "Unnamed alternative")),
    );
  const delay =
    typeof timing.delay_seconds === "number"
      ? `${timing.delay_seconds / 60}-minute nominal delay`
      : "Feed delay not recorded";
  const columns = weighted ? 7 : 6;

  if (content.schema_version !== "instrument_comparison.v1")
    return (
      <section className={styles.comparison} aria-label="Instrument comparison">
        <p className={styles.warning}>
          A supported instrument comparison is unavailable in this record.
        </p>
        <JsonDetails
          title="Inspect saved comparison"
          value={artifact.content}
        />
      </section>
    );

  return (
    <section className={styles.comparison} aria-label="Instrument comparison">
      <div className={styles.kicker}>
        <span>
          <Columns3 size={14} aria-hidden="true" />
          THESIS EXPRESSIONS
        </span>
        <span>Saved comparison · Research only</span>
      </div>
      <div className={styles.heading}>
        <div>
          <h3>
            {text(content.underlying)}
            <span> at expiration</span>
          </h3>
          <p>
            {text(
              content.purpose,
              "Compare the recorded alternatives under shared expiration assumptions.",
            )}
          </p>
        </div>
      </div>
      {synthetic && (
        <p className={styles.synthetic}>
          <AlertTriangle size={15} aria-hidden="true" />
          <strong>Synthetic fixture</strong> · Conditional arithmetic for
          testing, not investment evidence.
        </p>
      )}
      <dl className={styles.context}>
        <div>
          <dt>Capital per alternative</dt>
          <dd>
            {amount(content.capital)}
            {content.currency === "USD" && <small> USD</small>}
          </dd>
        </div>
        <div>
          <dt>Expiration / scenario horizon</dt>
          <dd>{text(content.expiration)}</dd>
          {typeof content.scenario_horizon === "string" &&
            content.scenario_horizon !== content.expiration && (
              <small>{content.scenario_horizon}</small>
            )}
        </div>
        <div>
          <dt>Information cutoff</dt>
          <dd className={styles.smallValue}>
            {timestamp(content.information_cutoff)}
          </dd>
        </div>
      </dl>
      <p className={styles.scope}>
        Each alternative independently uses the same capital and scenarios.
        Whole-unit quantities use explicit investigator requests when provided,
        or maximum affordable sizing by default under recorded entry costs.
        Unused capital remains cash. These hypothetical alternatives must not be
        combined as simultaneous allocations of the same capital.
      </p>
      <div className={styles.hypothesis}>
        <span>BOUND HYPOTHESIS</span>
        <h4>{text(hypothesis.title, "Hypothesis title not recorded")}</h4>
        <p>{text(hypothesis.prediction, "Prediction not recorded.")}</p>
      </div>
      <div className={styles.warning}>
        <Clock3 size={16} aria-hidden="true" />
        <p>
          Conditional expiration arithmetic · No execution eligibility. Option
          prices come from a saved chain with {delay.toLowerCase()}. This report
          does not establish fill availability, predictive edge, or a preferred
          instrument.
        </p>
      </div>

      <section
        className={styles.section}
        aria-labelledby="instrument-capital-heading"
      >
        <div className={styles.sectionHeading}>
          <div>
            <span>01 / CAPITAL & DOWNSIDE</span>
            <h4 id="instrument-capital-heading">
              What each expression requires
            </h4>
          </div>
          <small>Base entry assumptions</small>
        </div>
        <div className={styles.tableWrap}>
          <table
            className={styles.capitalTable}
            aria-label="Instrument capital and downside comparison"
          >
            <thead>
              <tr>
                <th scope="col">Alternative</th>
                <th scope="col">Hypothetical size</th>
                <th scope="col">Entry cost</th>
                <th scope="col">Cash left</th>
                <th scope="col">Expiry loss bound</th>
                <th scope="col">Worst scenario P&amp;L</th>
                {weighted && <th scope="col">Assumption-weighted P&amp;L</th>}
              </tr>
            </thead>
            <tbody>
              {candidates.map((candidate, index) => {
                const base =
                  candidate.status === "available"
                    ? computed(candidate.base)
                    : null;
                return (
                  <tr key={text(candidate.candidate_id, String(index))}>
                    <th scope="row">
                      <strong>{candidateName(candidate)}</strong>
                      <span className={styles.instrumentType}>
                        {label(text(candidate.instrument))}
                      </span>
                      {base && <span className={styles.modeled}>Modeled</span>}
                    </th>
                    {base ? (
                      <>
                        <td>
                          <span className={styles.mobileLabel}>
                            Hypothetical size
                          </span>
                          {quantity(base)}
                          <span className={styles.instrumentType}>
                            {sizingBasis(candidate)}
                          </span>
                        </td>
                        <td>
                          <span className={styles.mobileLabel}>Entry cost</span>
                          {amount(base.entry_cost)}
                        </td>
                        <td>
                          <span className={styles.mobileLabel}>Cash left</span>
                          {amount(base.remaining_cash)}
                        </td>
                        <td>
                          <span className={styles.mobileLabel}>
                            Expiry loss bound
                          </span>
                          {amount(base.expiry_loss_bound)}
                        </td>
                        <td className={signClass(base.scenario_worst_pnl)}>
                          <span className={styles.mobileLabel}>
                            Worst scenario P&amp;L
                          </span>
                          {amount(base.scenario_worst_pnl)}
                        </td>
                        {weighted && (
                          <td
                            className={signClass(base.assumption_weighted_pnl)}
                          >
                            <span className={styles.mobileLabel}>
                              Assumption-weighted P&amp;L
                            </span>
                            {amount(base.assumption_weighted_pnl)}
                          </td>
                        )}
                      </>
                    ) : (
                      <td colSpan={columns - 1} className={styles.unavailable}>
                        <strong>Unavailable for comparison</strong>
                        <Issues value={candidate.issues} />
                        {records(candidate.issues).length === 0 && (
                          <p>No usable calculation was recorded.</p>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {candidates.length === 0 && (
          <p className={styles.empty}>
            No candidate calculations were recorded.
          </p>
        )}
        <p className={styles.note}>
          The expiry loss bound is a modeled maximum capital loss over
          nonnegative expiration prices, including recorded fees and cash
          return. The worst supplied scenario covers only this scenario grid.
          Neither measures pre-expiry, assignment, funding, or operational risk.
        </p>
        {!weighted && (
          <p className={styles.unweighted}>
            No complete probability assumptions were recorded. Weighted P&amp;L
            and weighted excess over cash are not shown.
          </p>
        )}
      </section>

      <section
        className={styles.section}
        aria-labelledby="instrument-scenarios-heading"
      >
        <div className={styles.sectionHeading}>
          <div>
            <span>02 / SHARED SCENARIOS</span>
            <h4 id="instrument-scenarios-heading">
              Outcomes at the same expiration
            </h4>
          </div>
        </div>
        {typeof content.scenario_rationale === "string" && (
          <p className={styles.sectionIntro}>{content.scenario_rationale}</p>
        )}
        <p className={styles.note}>
          Underlying prices
          {weighted
            ? " and probabilities are investigator-supplied assumptions"
            : " are investigator-supplied assumptions"}
          . Cells show hypothetical P&amp;L and total terminal capital,
          including unused cash.
        </p>
        <div
          className={styles.modeButtons}
          role="group"
          aria-label="Scenario entry cost assumptions"
        >
          <button
            type="button"
            aria-pressed={scenarioMode === "base"}
            onClick={() => setScenarioMode("base")}
          >
            Base costs
          </button>
          <button
            type="button"
            aria-pressed={scenarioMode === "adverse"}
            onClick={() => setScenarioMode("adverse")}
          >
            Adverse costs · same quantity
          </button>
        </div>
        {scenarios.length > 0 && candidates.length > 0 ? (
          <div
            className={styles.matrixWrap}
            role="region"
            aria-label="Scenario outcome matrix"
            tabIndex={0}
          >
            <table
              className={styles.matrix}
              aria-label="Hypothetical expiration scenario outcomes"
            >
              <thead>
                <tr>
                  <th scope="col">Expiry assumption</th>
                  {candidates.map((candidate, i) => (
                    <th scope="col" key={i}>
                      {candidateName(candidate)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map((scenario, i) => (
                  <tr key={i}>
                    <th scope="row">
                      <strong>{text(scenario.label)}</strong>
                      <span>
                        Underlying {amount(scenario.underlying_at_expiry)}
                      </span>
                      <small>
                        {weighted
                          ? `${percent(scenario.probability)} assumed probability`
                          : "Probability not assigned"}
                      </small>
                    </th>
                    {candidates.map((candidate, j) => {
                      const result =
                        candidate.status === "available"
                          ? computed(candidate[scenarioMode])
                          : null;
                      const outcome = result
                        ? records(result.scenarios).find(
                            (entry) => entry.label === scenario.label,
                          )
                        : null;
                      return (
                        <td key={j}>
                          {outcome ? (
                            <>
                              <strong className={signClass(outcome.pnl)}>
                                {amount(outcome.pnl)}
                              </strong>
                              <span>
                                {amount(outcome.terminal_capital)} terminal
                              </span>
                              <small>
                                Conditional P&amp;L / capital:{" "}
                                {percent(outcome.return_on_capital)}
                              </small>
                            </>
                          ) : (
                            <span className={styles.unavailableText}>
                              {record(candidate[scenarioMode]).status ===
                              "not_affordable"
                                ? "Over budget at this cost"
                                : "Unavailable"}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={styles.empty}>
            No shared scenario outcomes were recorded.
          </p>
        )}
        <p className={styles.note}>
          The scenario grid is not a probability forecast or an exhaustive set
          of outcomes. No alternative is ranked or selected by this report.
        </p>
      </section>

      <section
        className={styles.section}
        aria-labelledby="instrument-stress-heading"
      >
        <div className={styles.sectionHeading}>
          <div>
            <span>03 / ENTRY COST SENSITIVITY</span>
            <h4 id="instrument-stress-heading">
              Keep the position, stress the cost
            </h4>
          </div>
          <small>
            {text(assumptions.adverse_price_bps, "Unrecorded")} bps adverse
            prices
          </small>
        </div>
        <p className={styles.sectionIntro}>
          Adverse costs keep each base quantity fixed. A position that exceeds
          the shared budget stays visibly over budget; the calculation does not
          resize or borrow.
        </p>
        <div className={styles.tableWrap}>
          <table
            className={styles.stressTable}
            aria-label="Adverse entry cost comparison"
          >
            <thead>
              <tr>
                <th scope="col">Alternative</th>
                <th scope="col">Same quantity</th>
                <th scope="col">Stressed entry cost</th>
                <th scope="col">Cash left / budget</th>
                <th scope="col">Worst scenario P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((candidate, index) => {
                const adverse = record(candidate.adverse);
                const result =
                  candidate.status === "available" ? computed(adverse) : null;
                const overBudget =
                  candidate.status === "available" &&
                  adverse.status === "not_affordable";
                return (
                  <tr key={index}>
                    <th scope="row">{candidateName(candidate)}</th>
                    <td>
                      <span className={styles.mobileLabel}>Same quantity</span>
                      {candidate.status === "available"
                        ? quantity(adverse)
                        : "—"}
                      {candidate.status === "available" && (
                        <span className={styles.instrumentType}>
                          {sizingBasis(candidate)}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={styles.mobileLabel}>
                        Stressed entry cost
                      </span>
                      {result
                        ? amount(result.entry_cost)
                        : overBudget
                          ? amount(adverse.required_capital)
                          : "—"}
                    </td>
                    <td>
                      <span className={styles.mobileLabel}>
                        Cash left / budget
                      </span>
                      {overBudget ? (
                        <span className={styles.overBudget}>Over budget</span>
                      ) : result ? (
                        amount(result.remaining_cash)
                      ) : (
                        "Unavailable"
                      )}
                      {!result && <Issues value={adverse.issues} />}
                    </td>
                    <td
                      className={
                        result
                          ? signClass(result.scenario_worst_pnl)
                          : undefined
                      }
                    >
                      <span className={styles.mobileLabel}>
                        Worst scenario P&amp;L
                      </span>
                      {result ? amount(result.scenario_worst_pnl) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section
        className={styles.section}
        aria-labelledby="instrument-inputs-heading"
      >
        <div className={styles.sectionHeading}>
          <div>
            <span>04 / INPUTS & ASSUMPTIONS</span>
            <h4 id="instrument-inputs-heading">
              What this comparison depends on
            </h4>
          </div>
        </div>
        <div className={styles.stockReference}>
          <div>
            <h5>Stock reference</h5>
            <strong>
              {amount(stock.price)}{" "}
              <span>{text(stock.underlying, text(content.underlying))}</span>
            </strong>
          </div>
          <span className={styles.referenceBadge}>
            {stock.observation_session || stock.source_artifact_id
              ? "Dataset close · hypothetical entry"
              : stock.assumption === true
                ? "Explicit price assumption"
                : Object.keys(stock).length > 0
                  ? "Recorded reference"
                  : "Stock reference unavailable"}
          </span>
          <p>{text(stock.rationale, "Reference rationale not recorded.")}</p>
          <dl>
            <div>
              <dt>Source</dt>
              <dd>{text(stock.source)}</dd>
            </div>
            <div>
              <dt>Source price basis</dt>
              <dd>
                {typeof stock.source_price_basis === "string"
                  ? label(stock.source_price_basis)
                  : stock.assumption === true
                    ? "Assumed price; no dataset basis"
                    : "Not recorded"}
              </dd>
            </div>
            <div>
              <dt>Observation time</dt>
              <dd>{timestamp(stock.observed_at)}</dd>
            </div>
            {typeof stock.observation_session === "string" && (
              <div>
                <dt>Observation session</dt>
                <dd>{stock.observation_session}</dd>
              </div>
            )}
            <div>
              <dt>Reference received</dt>
              <dd>{timestamp(stock.received_at)}</dd>
            </div>
            <div>
              <dt>Options chain received</dt>
              <dd>{timestamp(timing.chain_received_at)}</dd>
            </div>
            <div>
              <dt>Options acquisition started</dt>
              <dd>{timestamp(timing.acquisition_started_at)}</dd>
            </div>
            <div>
              <dt>Corporate actions checked</dt>
              <dd>
                {stock.corporate_actions_checked === true
                  ? "Declared checked in source"
                  : stock.corporate_actions_checked === false
                    ? "Not checked"
                    : "Not recorded"}
              </dd>
            </div>
            {typeof stock.source_path === "string" && (
              <div>
                <dt>Retained dataset location</dt>
                <dd>
                  <code>
                    {text(stock.source_artifact_id)}
                    {stock.source_path}
                  </code>
                </dd>
              </div>
            )}
          </dl>
          {typeof stock.share_basis_assumption === "string" && (
            <div className={styles.shareBasis}>
              <h5>Share-basis comparability assumption</h5>
              <p>{stock.share_basis_assumption}</p>
              <p className={styles.note}>
                The source dataset value is retained unchanged. No share-basis
                conversion is inferred.
              </p>
            </div>
          )}
          {Array.isArray(stock.corporate_actions) && (
            <div className={styles.corporateActions}>
              {records(stock.corporate_actions).length > 0 ? (
                <details>
                  <summary>
                    Retained corporate actions ·{" "}
                    {records(stock.corporate_actions).length}
                  </summary>
                  <dl>
                    {records(stock.corporate_actions).map((action, i) => (
                      <div key={i}>
                        <dt>
                          {text(action.session)} · {label(text(action.kind))}
                        </dt>
                        <dd>Source value: {text(action.value)}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              ) : (
                <p className={styles.note}>
                  No corporate-action records are attached. This does not
                  establish that no actions occurred.
                </p>
              )}
            </div>
          )}
          {texts(stock.limitations).length > 0 && (
            <ul className={styles.stockLimitations}>
              {texts(stock.limitations).map((limitation, index) => (
                <li key={index}>{limitation}</li>
              ))}
            </ul>
          )}
          <p className={styles.note}>
            Stock and option prices are separate references. Timing may differ,
            missing observation times remain unknown, and the chain is not an
            atomic snapshot.
          </p>
        </div>
        <dl className={styles.assumptionGrid}>
          <div>
            <dt>Option entry fee per contract</dt>
            <dd>{amount(assumptions.option_fee_per_contract)}</dd>
          </div>
          <div>
            <dt>Stock entry fee</dt>
            <dd>{amount(assumptions.stock_fee_flat)}</dd>
          </div>
          <div>
            <dt>Cash return over this horizon</dt>
            <dd>{percent(assumptions.cash_return_over_horizon)}</dd>
          </div>
          <div>
            <dt>Adverse entry price change</dt>
            <dd>{text(assumptions.adverse_price_bps)} bps</dd>
          </div>
        </dl>
        <div className={styles.contractAssumption}>
          <h5>
            {assumptions.standard_contract_mode === "hypothetical_100_share_usd"
              ? "Hypothetical 100-share / 100-multiplier USD terms"
              : "Recorded standard-contract assumption"}
          </h5>
          <p>
            {text(
              assumptions.standard_contract_assumption,
              "No standard-contract assumption was recorded.",
            )}
          </p>
          <p className={styles.note}>
            These terms are research assumptions. The saved chain does not
            verify the premium multiplier, share deliverable or settlement
            terms.
          </p>
        </div>
        <div className={styles.candidateDetails}>
          {candidates.map((candidate, index) => {
            const base =
              candidate.status === "available"
                ? computed(candidate.base)
                : null;
            const adverse =
              candidate.status === "available"
                ? computed(candidate.adverse)
                : null;
            return (
              <details key={index}>
                <summary>
                  {candidateName(candidate)}
                  <span>Rationale, costs &amp; source legs</span>
                </summary>
                <div className={styles.detailBody}>
                  <h5>Investigator rationale</h5>
                  <p>{text(candidate.rationale, "No rationale recorded.")}</p>
                  <Issues value={candidate.issues} />
                  {base && (
                    <dl className={styles.assumptionGrid}>
                      <div>
                        <dt>Base entry fees</dt>
                        <dd>{amount(base.fees)}</dd>
                      </div>
                      <div>
                        <dt>Position-only expiry loss bound</dt>
                        <dd>{amount(base.position_expiry_loss_bound)}</dd>
                      </div>
                      {weighted && (
                        <>
                          <div>
                            <dt>Base weighted excess over cash</dt>
                            <dd>{amount(base.excess_vs_cash)}</dd>
                          </div>
                          <div>
                            <dt>Adverse weighted P&amp;L</dt>
                            <dd>
                              {adverse
                                ? amount(adverse.assumption_weighted_pnl)
                                : "Unavailable"}
                            </dd>
                          </div>
                        </>
                      )}
                    </dl>
                  )}
                  {records(candidate.legs).length > 0 && (
                    <div className={styles.legs}>
                      {records(candidate.legs).map((leg, i) => (
                        <div key={i}>
                          <h5>
                            {text(leg.side, "Source leg")} ·{" "}
                            {text(leg.symbol, text(leg.underlying))}
                          </h5>
                          <dl>
                            {Object.entries(leg)
                              .filter(
                                ([, value]) =>
                                  value === null ||
                                  typeof value === "string" ||
                                  typeof value === "number" ||
                                  typeof value === "boolean",
                              )
                              .map(([key, value]) => (
                                <div key={key}>
                                  <dt>{label(key)}</dt>
                                  <dd>
                                    {value === null
                                      ? "Not recorded"
                                      : typeof value === "boolean"
                                        ? value
                                          ? "Yes"
                                          : "No"
                                        : String(value)}
                                  </dd>
                                </div>
                              ))}
                          </dl>
                          <Issues value={leg.issues} />
                          {texts(leg.source_issues).length > 0 && (
                            <p className={styles.note}>
                              Retained source flags:{" "}
                              {texts(leg.source_issues).map(label).join(" · ")}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </details>
            );
          })}
        </div>
        {texts(content.limitations).length > 0 && (
          <details className={styles.limitations}>
            <summary>
              Model limitations · {texts(content.limitations).length}
            </summary>
            <ul>
              {texts(content.limitations).map((limitation, index) => (
                <li key={index}>{limitation}</li>
              ))}
            </ul>
          </details>
        )}
        <details className={styles.provenance}>
          <summary>Frozen input versions</summary>
          <Binding
            title="Hypothesis"
            value={bindings.hypothesis ?? content.hypothesis}
          />
          <Binding title="Options chain" value={bindings.chain} />
          {bindings.stock != null && (
            <Binding title="Stock source" value={bindings.stock} />
          )}
          {records(bindings.scenario_sources).map((source, index) => (
            <Binding
              key={index}
              title={`Scenario source ${index + 1}`}
              value={source}
            />
          ))}
        </details>
      </section>
      <JsonDetails title="Inspect saved comparison" value={artifact.content} />
    </section>
  );
}
