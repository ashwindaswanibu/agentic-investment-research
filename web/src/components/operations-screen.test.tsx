import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsScreen } from "./operations-screen";
import {
  ObservedEquityChart,
  PaperPerformancePanel,
} from "./paper-performance";
import { capsFixture } from "@/test/fixtures";
import {
  mandateFixture,
  mandateValues,
  operationsFixture,
} from "@/test/paper-fixtures";

const access = vi.hoisted(() => ({ canWrite: true, readOnly: false }));
vi.mock("./app-shell", () => ({
  useEnvironment: () => ({
    canWrite: access.canWrite,
    capabilities: { ...capsFixture, read_only: access.readOnly },
    capabilityError: null,
  }),
}));
beforeEach(() => {
  access.canWrite = true;
  access.readOnly = false;
});
afterEach(() => vi.unstubAllGlobals());
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

describe("paper operator controls", () => {
  it("disables every mutation in read-only mode and invents no operation history", async () => {
    access.canWrite = false;
    access.readOnly = true;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response(operationsFixture)),
    );
    render(<OperationsScreen />);
    await screen.findByText("Control version 3");
    for (const name of [
      "Activate selected mandate",
      "Set exit only",
      "Halt orders",
      "New mandate",
    ])
      expect(screen.getByRole("button", { name })).toBeDisabled();
    expect(
      screen.getByText("No worker cycle has been recorded."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No valuation observations have been recorded."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Positions remain held/)).toBeInTheDocument();
  });
  it("saves an explicit immutable mandate and activates only after a separate action", async () => {
    const empty = {
      ...operationsFixture,
      control: { version: 3, mode: "halted", mandate_id: null },
      mandate: null,
      mandates: [],
    };
    const fetcher = vi.fn((url: string, options?: RequestInit) =>
      Promise.resolve(
        response(
          options?.method === "POST"
            ? url.endsWith("/mandates")
              ? mandateFixture
              : { version: 4, mode: "active", mandate_id: mandateFixture.id }
            : empty,
        ),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsScreen />);
    await screen.findByText("No mandate has been saved");
    fireEvent.click(screen.getByRole("button", { name: "New mandate" }));
    const form = screen
      .getByRole("button", { name: "Save inactive mandate" })
      .closest("form")!;
    for (const input of Array.from(form.querySelectorAll("input")))
      expect(input.value).toBe("");
    fireEvent.submit(form);
    expect(
      await screen.findByText(/Complete every mandate field/),
    ).toBeInTheDocument();
    for (const [key, value] of Object.entries(mandateValues))
      fireEvent.change(form.querySelector(`#mandate-${key}`)!, {
        target: { value },
      });
    fireEvent.submit(form);
    await screen.findByText(/Mandate saved as an immutable version/);
    const savedPosts = fetcher.mock.calls.filter(
      ([, options]) => options?.method === "POST",
    );
    expect(savedPosts).toHaveLength(1);
    expect(savedPosts[0][0]).toBe("/api/paper/mandates");
    expect(
      JSON.parse(String(savedPosts[0][1]?.body)).policy.max_order_notional,
    ).toBe("1250.50");
    fireEvent.click(
      screen.getByRole("button", { name: "Activate selected mandate" }),
    );
    await waitFor(() =>
      expect(
        fetcher.mock.calls.filter(([, options]) => options?.method === "POST"),
      ).toHaveLength(2),
    );
    const last = fetcher.mock.calls.find(([url]) =>
      url.endsWith("/operations/control"),
    )!;
    expect(JSON.parse(String(last[1]?.body))).toEqual({
      mandate_id: "test-mandate",
      mode: "active",
      expected_version: 3,
    });
  });
  it("refreshes a 409 control conflict and never retries activation automatically", async () => {
    let reads = 0;
    const fetcher = vi.fn((_url: string, options?: RequestInit) => {
      if (options?.method === "POST")
        return Promise.resolve(
          response(
            {
              error: {
                code: "CONTROL_CONFLICT",
                message: "Another operator changed the mode.",
              },
            },
            409,
          ),
        );
      reads += 1;
      return Promise.resolve(
        response({
          ...operationsFixture,
          control: { ...operationsFixture.control, version: reads > 1 ? 4 : 3 },
        }),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsScreen />);
    await screen.findByText("Control version 3");
    fireEvent.click(
      screen.getByRole("button", { name: "Activate selected mandate" }),
    );
    await screen.findByText("Control version 4");
    expect(
      screen.getByText(/Operations changed in another session/),
    ).toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(([, options]) => options?.method === "POST"),
    ).toHaveLength(1);
  });
  it("retains a specific admission error instead of mislabelling every 409 as a race", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, options?: RequestInit) =>
        Promise.resolve(
          options?.method === "POST"
            ? response(
                {
                  error: {
                    code: "ACCOUNT_REQUIRED",
                    message:
                      "Open the paper account before activating operations.",
                  },
                },
                409,
              )
            : response(operationsFixture),
        ),
      ),
    );
    render(<OperationsScreen />);
    await screen.findByText("Control version 3");
    fireEvent.click(
      screen.getByRole("button", { name: "Activate selected mandate" }),
    );
    expect(
      await screen.findByText(
        /Open the paper account before activating operations/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Operations changed in another session/),
    ).toBeNull();
  });
  it("keeps saved inactive versions selectable after reload and blocks expired activation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          ...operationsFixture,
          control: { version: 3, mode: "halted", mandate_id: null },
          mandate: null,
          mandates: [
            {
              ...mandateFixture,
              payload: {
                ...mandateFixture.payload,
                expires_at: "2001-01-01T12:00:00Z",
              },
            },
          ],
        }),
      ),
    );
    render(<OperationsScreen />);
    await screen.findByText("Control version 3");
    expect(
      screen.getByRole("combobox", { name: "Saved mandate version" }),
    ).toHaveValue("test-mandate");
    expect(
      screen.getByRole("button", { name: "Activate selected mandate" }),
    ).toBeDisabled();
    expect(screen.getByText(/This mandate has expired/)).toBeInTheDocument();
  });
});

describe("observed paper performance", () => {
  it("explains incomplete calendar coverage when observations exist without adding an initial empty-state warning", () => {
    const performance = {
      equity_series: [],
      daily: [],
      latest: null,
      calendar_coverage: {
        complete: false,
        start: null,
        end: null,
        verified_at: null,
        reason: "CALENDAR_COVERAGE_MISSING",
      },
    };
    const { rerender } = render(
      <PaperPerformancePanel performance={performance} />,
    );
    expect(screen.queryByText(/calendar coverage is incomplete/)).toBeNull();
    rerender(
      <PaperPerformancePanel
        performance={{
          ...performance,
          latest: {
            equity: "1000",
            cash: "1000",
            observed_at: "2026-10-05T16:00:00Z",
          },
        }}
      />,
    );
    expect(
      screen.getByText(/calendar coverage is incomplete/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Daily comparisons remain unavailable/),
    ).toBeInTheDocument();
  });
  it("distinguishes the report time from an older valuation observation", () => {
    render(
      <PaperPerformancePanel
        performance={{
          equity_series: [],
          daily: [],
          report_as_of: "2026-10-05T16:15:00Z",
          latest: {
            observed_at: "2026-10-05T16:00:00Z",
            equity: "1000",
            cash: "1000",
            intraday: {},
            since_opening: {},
          },
        }}
      />,
    );
    expect(
      screen.getByText(/latest valuation is older than this report/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Report as of/)).toBeInTheDocument();
  });
  it("keeps missing valuations and baselines unavailable while showing known accounting deltas", () => {
    render(
      <PaperPerformancePanel
        performance={{
          equity_series: [],
          daily: [
            {
              session: "2026-10-05",
              close_status: "missing",
              close_equity: null,
              net_pnl: null,
              net_return: null,
              fees_delta: null,
              fills_delta: null,
              baseline: null,
              gap_reason: "no_qualifying_close",
            },
          ],
          latest: {
            observed_at: "2026-10-05T16:00:00Z",
            equity: null,
            reported_equity: "1500",
            gap_reason: "missing_quotes",
            missing_symbols: ["TEST"],
            cash: "900",
            intraday: {
              baseline: null,
              net_pnl: null,
              net_return: null,
              realized_pnl_delta: "10",
              fees_delta: "2",
              fills_delta: 1,
            },
            since_opening: { net_pnl: null },
          },
        }}
      />,
    );
    const equity = screen.getByText("Observed equity").closest("div")!;
    expect(within(equity).getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("$1,500.00")).toBeNull();
    expect(screen.getByText("$10.00")).toBeInTheDocument();
    expect(
      screen.getByText(/Session baseline: Unavailable/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Missing marks: TEST/)).toBeInTheDocument();
  });
  it("plots separate segments around unavailable observations rather than joining the gap", () => {
    const points = ["1000", "1010", null, "1020", "1030"].map(
      (equity, index) => ({
        observed_at: `2026-10-05T16:0${index}:00Z`,
        equity,
        gap_reason: equity === null ? "missing_quotes" : null,
      }),
    );
    const { container } = render(<ObservedEquityChart points={points} />);
    expect(container.querySelectorAll("[data-equity-segment]")).toHaveLength(2);
    expect(screen.getByRole("img")).toHaveAccessibleName(
      /5 observations, 1 unavailable/,
    );
  });
  it.each([
    ["1049", "1099"],
    ["1000.0001", "1000.0002"],
  ])(
    "keeps currency axis labels distinct for equity from %s to %s",
    (first, last) => {
      const { container } = render(
        <ObservedEquityChart
          points={[
            { observed_at: "2026-10-05T16:00:00Z", equity: first },
            { observed_at: "2026-10-05T16:01:00Z", equity: last },
          ]}
        />,
      );
      const ticks = Array.from(container.querySelectorAll("svg g text")).map(
        (tick) => tick.textContent,
      );
      expect(ticks).toHaveLength(3);
      expect(new Set(ticks).size).toBe(3);
      expect(ticks.every((tick) => tick?.startsWith("$"))).toBe(true);
      expect(ticks.some((tick) => tick?.includes("K"))).toBe(false);
    },
  );
  it("renders supplied net P&L without deducting fees again and converts fractional returns once", () => {
    render(
      <PaperPerformancePanel
        performance={{
          equity_series: [],
          daily: [],
          latest: {
            equity: "1050",
            cash: "900",
            observed_at: "2026-10-05T16:00:00Z",
            since_opening: { net_pnl: "50" },
            intraday: {
              net_pnl: "50",
              net_return: "0.05",
              fees_delta: "2",
              realized_pnl_delta: "30",
              fills_delta: 1,
              baseline: { kind: "account_opening", equity: "1000" },
            },
          },
        }}
      />,
    );
    const current = screen.getByText("Current-session P&L").closest("div")!;
    expect(within(current).getByText("$50.00")).toBeInTheDocument();
    expect(screen.getByText("5.00%")).toBeInTheDocument();
    expect(screen.queryByText("$48.00")).toBeNull();
  });
});
