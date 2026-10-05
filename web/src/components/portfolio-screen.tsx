"use client";
import Link from "next/link";
import { RefreshCw, Settings2, ShieldCheck, Wallet } from "lucide-react";
import { parsePortfolio } from "@/lib/contracts";
import { useResource } from "@/lib/use-resource";
import { dateTime, label, money, scalar } from "@/lib/format";
import { EmptyState, ErrorNotice, JsonDetails, Loading } from "./ui";

export function PortfolioScreen() {
  const portfolio = useResource("/paper/portfolio", parsePortfolio, 10_000);
  const data = portfolio.data;
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">DETERMINISTIC PAPER LEDGER</div>
          <h1>Paper portfolio</h1>
          <p>
            Track paper decisions, positions, and the accounting events behind
            them.
          </p>
        </div>
        <div className="page-heading-actions">
          <Link href="/operations" className="button button-secondary">
            <Settings2 size={15} />
            Operations
          </Link>
          <button
            className="button button-secondary"
            onClick={() => void portfolio.refresh()}
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
            No live brokerage connection. Positions and balances come from the
            recorded paper ledger.
          </span>
        </div>
      </div>
      {portfolio.error && (
        <ErrorNotice stale={!!data} onRetry={() => void portfolio.refresh()}>
          {portfolio.error}
        </ErrorNotice>
      )}
      {portfolio.loading ? (
        <Loading label="Loading paper ledger…" />
      ) : (
        data && (
          <>
            {data.initialized === false && (
              <div className="info-notice">
                A paper account has not been initialized. No orders can be
                recorded yet.
              </div>
            )}
            {data.equity === null && (
              <div className="info-notice">
                Portfolio equity is unavailable because current attributable
                marks are missing. Cash and realized P&amp;L remain recorded
                separately.
              </div>
            )}
            <div className="portfolio-summary">
              <div>
                <span>Portfolio equity</span>
                <strong>{money(data.equity)}</strong>
              </div>
              <div>
                <span>Cash</span>
                <strong>{money(data.cash)}</strong>
              </div>
              <div>
                <span>Realized P&L</span>
                <strong>{money(data.realized_pnl)}</strong>
              </div>
              <div>
                <span>Open positions</span>
                <strong>{data.positions.length}</strong>
              </div>
            </div>
            <section className="panel">
              <div className="panel-header">
                <h2>Positions</h2>
                <span className="muted">USD · recorded marks</span>
              </div>
              {data.positions.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Instrument</th>
                        <th>Quantity</th>
                        <th>Cost basis</th>
                        <th>Mark</th>
                        <th>Market value</th>
                        <th>Unrealized P&L</th>
                        <th>Marked at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.positions.map((position, index) => (
                        <tr key={String(position.symbol || index)}>
                          <td className="strong">{scalar(position.symbol)}</td>
                          <td>{scalar(position.quantity)}</td>
                          <td>
                            {money(
                              typeof position.cost_basis === "string"
                                ? position.cost_basis
                                : null,
                            )}
                          </td>
                          <td>
                            {money(
                              typeof position.mark === "string"
                                ? position.mark
                                : null,
                            )}
                          </td>
                          <td>
                            {money(
                              typeof position.market_value === "string"
                                ? position.market_value
                                : null,
                            )}
                          </td>
                          <td>
                            {money(
                              typeof position.unrealized_pnl === "string"
                                ? position.unrealized_pnl
                                : null,
                            )}
                          </td>
                          <td>
                            {dateTime(
                              typeof position.marked_at === "string"
                                ? position.marked_at
                                : null,
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  title="No open paper positions"
                  description="Positions appear after a reviewed strategy produces an eligible paper intent and the deterministic execution checks succeed."
                  icon={<Wallet size={26} strokeWidth={1.4} />}
                />
              )}
            </section>
            <section className="panel ledger-panel">
              <div className="panel-header">
                <h2>
                  Ledger events{" "}
                  <span className="count">{data.events.length}</span>
                </h2>
                <span className="muted">Replayable accounting history</span>
              </div>
              {data.events.length ? (
                <div className="ledger-events">
                  {data.events.map((event, index) => (
                    <div key={String(event.id || index)}>
                      <div className="ledger-event-heading">
                        <strong>
                          {label(
                            String(event.kind || event.type || "Ledger event"),
                          )}
                        </strong>
                        <span>
                          {dateTime(
                            typeof event.created_at === "string"
                              ? event.created_at
                              : typeof event.timestamp === "string"
                                ? event.timestamp
                                : null,
                          )}
                        </span>
                      </div>
                      <JsonDetails title="Event record" value={event} />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="quiet-empty">
                  No ledger events are available.
                </div>
              )}
            </section>
            <p className="page-note">
              {data.account_id ? (
                <>
                  Account <span className="mono">{data.account_id}</span>.{" "}
                </>
              ) : (
                "No paper account initialized. "
              )}
              Valuation depends on recorded market marks; refresh does not imply
              a new market quote.
              {data.valuation_basis && <> Basis: {data.valuation_basis}.</>}
            </p>
          </>
        )
      )}
    </div>
  );
}
