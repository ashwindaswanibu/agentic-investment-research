// Synthetic display fixtures, not financial results.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseArtifact, type JsonObject } from "@/lib/contracts";
import { artifactFixture } from "@/test/fixtures";
import { ArtifactContent, ExperimentContent } from "./artifacts";
import { StrategyAssessment } from "./strategy-assessment";

const report: JsonObject = {
  schema_version: "strategy-assessment.v1",
  status: "assessed",
  headline: "This simulation lost money.",
  basis: "historical_simulation",
  edge_status: "unestablished",
  synthetic_data: true,
  periods: [
    {
      start_session: "2020-01-01",
      end_session: "2020-01-03",
      sessions: 3,
      fill_count: 1,
      net_return: "-0.1",
      max_drawdown: "0.1",
      invested_sessions: 2,
      mean_close_exposure: "0.3",
      baselines: {
        cash: { net_return: "0", difference: "-0.1" },
        buy_hold: { net_return: "-0.2", difference: "0.1" },
      },
    },
  ],
  checks: [
    {
      code: "holdout",
      status: "missing",
      message: "No protected final holdout recorded.",
    },
  ],
};
describe("automatic strategy assessments", () => {
  it("shows a loss despite beating a falling benchmark and exposes cash and allocation", () => {
    render(<StrategyAssessment value={report} />);
    expect(screen.getByText("This simulation lost money.")).toBeInTheDocument();
    expect(screen.getByText("Edge unestablished")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("-10.00%")).toBeInTheDocument();
    expect(within(table).getByText("10.00 pp")).toBeInTheDocument();
    expect(within(table).getByText("-10.00 pp")).toBeInTheDocument();
    expect(
      screen.getByText(/Average allocation at the close: 30.00%/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Synthetic prices/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Evidence and validation gaps/));
    expect(
      screen.getByText("No protected final holdout recorded."),
    ).toBeVisible();
  });
  it("routes persisted reports and assessments embedded in new experiments", () => {
    const first = render(
      <ArtifactContent
        artifact={parseArtifact({
          ...artifactFixture,
          kind: "strategy_assessment",
          content: report,
        })}
      />,
    );
    expect(
      screen.getByRole("region", { name: "Strategy assessment" }),
    ).toBeInTheDocument();
    first.unmount();
    render(<ExperimentContent content={{ assessment: report }} />);
    expect(
      screen.getByRole("region", { name: "Strategy assessment" }),
    ).toBeInTheDocument();
  });
  it("retains the distinction between reset folds and a continuous account", () => {
    render(
      <StrategyAssessment
        value={{ ...report, basis: "reset_walk_forward_folds" }}
      />,
    );
    expect(
      screen.getByText(/Portfolios reset between test folds/),
    ).toBeInTheDocument();
  });
  it("keeps failure reasons open and does not manufacture metrics", () => {
    render(
      <StrategyAssessment
        value={{
          ...report,
          status: "unavailable",
          headline: "The recorded result cannot be assessed.",
          periods: [],
          checks: [
            {
              code: "invalid_record",
              status: "failed",
              message: "Inconsistent accounting",
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("Inconsistent accounting")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
