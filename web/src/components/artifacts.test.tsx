import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExperimentContent, ReviewContent, metricValue } from "./artifacts";
import { ToolCallView } from "./case-screen";
import { SourceLink } from "./ui";
import { parseToolCall } from "@/lib/contracts";
import { artifactFixture, toolFixture } from "@/test/fixtures";

describe("inspectable research output", () => {
  it("renders actual structured tool output as escaped text", () => {
    const { container } = render(
      <ToolCallView call={parseToolCall(toolFixture)} />,
    );
    fireEvent.click(screen.getByText("test_tool"));
    expect(screen.getByText(/alert\('untrusted'\)/)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("42 ms")).toBeInTheDocument();
  });
  it("retains rejected reviews and their exact version binding", () => {
    render(<ReviewContent content={artifactFixture.content} />);
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(
      screen.getByText("The held-out comparison failed."),
    ).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  });
  it("formats only known fraction metrics as percentages", () => {
    expect(metricValue("net_return", "0.05")).toBe("5.00%");
    expect(metricValue("max_drawdown", "0.125")).toBe("12.50%");
    expect(metricValue("sharpe", 0.8)).toBe("0.80");
    expect(metricValue("excess_return_vs_buy_hold", "-0.015")).toBe("-1.50 pp");
    expect(metricValue("net_return", null)).toBe("—");
    expect(metricValue("net_return", false)).toBe("No");
  });
  it("keeps six primary metrics separate from diagnostic assumptions", () => {
    render(
      <ExperimentContent
        content={{
          metrics: {
            net_return: "-0.05",
            final_equity: "95000",
            max_drawdown: "0.08",
            sharpe: -0.123456,
            fees: "12.50",
            fill_count: 4,
            sharpe_assumption:
              "Daily observations annualized using 252 sessions.",
            sharpe_observations: 42,
            realized_pnl: "-4000",
            initial_cash: "100000",
          },
        }}
      />,
    );
    const primary = screen.getByRole("group", {
      name: "Key experiment metrics",
    });
    expect(primary.children).toHaveLength(6);
    expect(within(primary).getByText("-0.12")).toBeInTheDocument();
    expect(within(primary).getByText("-5.00%")).toHaveClass("metric-negative");
    expect(within(primary).queryByText("Sharpe Assumption")).toBeNull();
    const diagnostics = screen
      .getByText("Metric diagnostics and assumptions")
      .closest("details");
    expect(diagnostics).not.toHaveAttribute("open");
    expect(screen.getByText("Realized P&L")).toBeInTheDocument();
  });
  it("plots only actual equity observations and displays baseline data separately", () => {
    render(
      <ExperimentContent
        content={{
          metrics: { net_return: "0.05", sharpe: null },
          equity_curve: [
            { session: "2026-01-01", equity: "100" },
            { session: "2026-01-02", equity: "105" },
          ],
          baseline: { cash: { net_return: "0", final_equity: "100" } },
        }}
      />,
    );
    expect(screen.getByRole("img")).toHaveAccessibleName(
      /from \$100.00 to \$105.00 across 2 sessions/,
    );
    expect(screen.getByText("Cash")).toBeInTheDocument();
    expect(screen.getAllByText("5.00%")).toHaveLength(1);
  });
  it("does not turn untrusted source schemes into executable links", () => {
    render(<SourceLink url="javascript:alert(1)" />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
