// Synthetic saved outputs only. These tests verify presentation, not investment results.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseArtifact, type JsonObject } from "@/lib/contracts";
import { artifactFixture } from "@/test/fixtures";
import { ArtifactContent } from "./artifacts";

const scenarios = [
  {
    label: "Downside assumption",
    underlying_at_expiry: "80",
    probability: "0.5",
  },
  {
    label: "Upside assumption",
    underlying_at_expiry: "120",
    probability: "0.5",
  },
];
function outcomes(pnls: string[], capitals: string[], returns: string[]) {
  return scenarios.map((scenario, i) => ({
    ...scenario,
    pnl: pnls[i],
    terminal_capital: capitals[i],
    return_on_capital: returns[i],
    excess_vs_cash: pnls[i],
  }));
}
const cash: JsonObject = {
  candidate_id: "cash",
  label: "Cash",
  instrument: "cash",
  status: "available",
  rationale: "Keep the shared capital at the explicitly assumed cash return.",
  issues: [],
  legs: [],
  base: {
    status: "computed",
    quantity: 0,
    quantity_unit: "cash",
    entry_cost: "0",
    remaining_cash: "1000",
    expiry_loss_bound: "0",
    position_expiry_loss_bound: "0",
    scenario_worst_pnl: "0",
    assumption_weighted_pnl: "0",
    excess_vs_cash: "0",
    fees: "0",
    scenarios: outcomes(["0", "0"], ["1000", "1000"], ["0", "0"]),
  },
};
cash.adverse = cash.base;
const stock: JsonObject = {
  candidate_id: "stock",
  label: "Underlying stock",
  instrument: "stock",
  status: "available",
  rationale: "Compare whole shares under the same supplied scenario grid.",
  issues: [],
  legs: [],
  base: {
    status: "computed",
    quantity: 9,
    quantity_unit: "shares",
    entry_cost: "910",
    remaining_cash: "90",
    expiry_loss_bound: "910",
    position_expiry_loss_bound: "910",
    scenario_worst_pnl: "-190",
    assumption_weighted_pnl: "-10",
    excess_vs_cash: "-10",
    fees: "10",
    scenarios: outcomes(["-190", "170"], ["810", "1170"], ["-0.19", "0.17"]),
  },
  adverse: {
    status: "computed",
    quantity: 9,
    quantity_unit: "shares",
    entry_cost: "919",
    remaining_cash: "81",
    expiry_loss_bound: "919",
    position_expiry_loss_bound: "919",
    scenario_worst_pnl: "-199",
    assumption_weighted_pnl: "-19",
    excess_vs_cash: "-19",
    fees: "10",
    scenarios: outcomes(["-199", "161"], ["801", "1161"], ["-0.199", "0.161"]),
  },
};
const call: JsonObject = {
  candidate_id: "call",
  label: "Nominated call",
  instrument: "long_call",
  status: "available",
  rationale:
    "Inspect the premium cost of this nominated call under shared assumptions.",
  issues: [],
  base: {
    status: "computed",
    quantity: 5,
    quantity_unit: "contracts",
    entry_cost: "1000",
    remaining_cash: "0",
    expiry_loss_bound: "1000",
    position_expiry_loss_bound: "1000",
    scenario_worst_pnl: "-1000",
    assumption_weighted_pnl: "4000",
    excess_vs_cash: "4000",
    fees: "0",
    scenarios: outcomes(["-1000", "9000"], ["0", "10000"], ["-1", "9"]),
  },
  adverse: {
    status: "not_affordable",
    quantity: 5,
    quantity_unit: "contracts",
    required_capital: "1010",
    remaining_cash: null,
    scenarios: [],
    issues: [
      {
        code: "adverse_budget_exceeded",
        message: "The unchanged position exceeds the budget at adverse prices.",
      },
    ],
  },
  legs: [
    {
      side: "buy",
      symbol: "TEST261016C00100000",
      selected_price: "2",
      market_at: "2026-10-05T14:00:00+00:00",
      received_at: "2026-10-05T14:15:00+00:00",
      contract_terms_status: "assumed_not_verified",
      source_issues: ["contract_deliverable_unverified"],
    },
  ],
};
const missing: JsonObject = {
  candidate_id: "put",
  label: "Nominated put",
  instrument: "long_put",
  status: "unavailable",
  rationale:
    "A nominated downside expression retained despite missing source data.",
  issues: [
    {
      code: "contract_missing",
      message: "The nominated put is absent from the saved chain.",
    },
  ],
  base: null,
  adverse: null,
  legs: [],
};
const assumptions: JsonObject = {
  currency: "USD",
  capital: "1000",
  scenarios,
  option_fee_per_contract: "0",
  stock_fee_flat: "10",
  cash_return_over_horizon: "0",
  adverse_price_bps: "100",
  standard_contract_mode: "hypothetical_100_share_usd",
  standard_contract_assumption:
    "Assume a 100-share deliverable and 100 premium multiplier for research only.",
};
const stockReference: JsonObject = {
  underlying: "TEST",
  price: "100",
  observed_at: null,
  received_at: null,
  source: "Investigator-supplied assumption; no market observation",
  assumption: true,
  rationale:
    "Explicit illustrative price assumption for the retained research question.",
};
const report: JsonObject = {
  schema_version: "instrument_comparison.v1",
  underlying: "TEST",
  expiration: "2026-10-16",
  currency: "USD",
  capital: "1000",
  assumptions,
  probability_basis: "supplied_scenario_assumptions",
  candidates: [cash, stock, call, missing],
  purpose:
    "Inspect conditional outcomes for a synthetic hypothesis without claiming a preferred instrument.",
  information_cutoff: "2026-10-05T15:00:00+00:00",
  scenario_horizon: "2026-10-16",
  scenario_rationale:
    "These are investigator-supplied scenario assumptions for software verification.",
  synthetic: true,
  execution_eligible: false,
  hypothesis: {
    id: "hypothesis-id",
    sha256: "a".repeat(64),
    title: "Synthetic hypothesis",
    prediction: "A synthetic prediction bound to retained evidence.",
    created_at: "2026-10-05T13:00:00+00:00",
  },
  source_bindings: {
    hypothesis: { id: "hypothesis-id", sha256: "a".repeat(64) },
    chain: { id: "chain-id", sha256: "b".repeat(64) },
    scenario_sources: [{ id: "scenario-source-id", sha256: "c".repeat(64) }],
  },
  timing: {
    chain_received_at: "2026-10-05T14:15:00+00:00",
    acquisition_started_at: "2026-10-05T14:14:59+00:00",
    delay_seconds: 900,
    atomic_snapshot: false,
    stock_reference: stockReference,
  },
  limitations: [
    "Spreads assume joint expiry settlement; analytical bounds exclude assignment and funding risk.",
  ],
};
function show(content: JsonObject = report) {
  return render(
    <ArtifactContent
      artifact={parseArtifact({
        ...artifactFixture,
        kind: "instrument_comparison",
        content,
        metadata: {},
      })}
    />,
  );
}

describe("saved instrument comparison", () => {
  it("counts two-leg spreads as spreads in both base and adverse views", () => {
    const base = {
      ...(call.base as JsonObject),
      quantity: 3,
      quantity_unit: "spreads",
      fees: "6",
      entry_cost: "606",
      remaining_cash: "394",
      expiry_loss_bound: "606",
      position_expiry_loss_bound: "606",
      scenario_worst_pnl: "-606",
      assumption_weighted_pnl: "894",
      excess_vs_cash: "894",
      scenarios: outcomes(
        ["-606", "2394"],
        ["394", "3394"],
        ["-0.606", "2.394"],
      ),
    };
    show({
      ...report,
      candidates: [
        cash,
        {
          ...call,
          label: "Three call spreads",
          instrument: "call_debit_spread",
          sizing_basis: "requested_quantity",
          requested_quantity: 3,
          legs: [],
          base,
          adverse: {
            ...base,
            entry_cost: "618",
            remaining_cash: "382",
            expiry_loss_bound: "618",
            position_expiry_loss_bound: "618",
            scenario_worst_pnl: "-618",
            assumption_weighted_pnl: "882",
            excess_vs_cash: "882",
            scenarios: outcomes(
              ["-618", "2382"],
              ["382", "3382"],
              ["-0.618", "2.382"],
            ),
          },
        },
      ],
    });
    for (const name of [
      "Instrument capital and downside comparison",
      "Adverse entry cost comparison",
    ]) {
      const table = screen.getByRole("table", { name });
      expect(within(table).getByText("3 spreads")).toBeVisible();
      expect(within(table).queryByText("3 contracts")).not.toBeInTheDocument();
    }
  });

  it("distinguishes investigator-requested quantities from maximum-affordable sizing without resizing stress", () => {
    const base = {
      ...(call.base as JsonObject),
      quantity: 3,
      entry_cost: "600",
      remaining_cash: "400",
      expiry_loss_bound: "600",
      position_expiry_loss_bound: "600",
      scenario_worst_pnl: "-600",
      assumption_weighted_pnl: "2400",
      excess_vs_cash: "2400",
      scenarios: outcomes(["-600", "5400"], ["400", "6400"], ["-0.6", "5.4"]),
    };
    const adverse = {
      ...base,
      quantity: 3,
      entry_cost: "606",
      remaining_cash: "394",
      expiry_loss_bound: "606",
      position_expiry_loss_bound: "606",
      scenario_worst_pnl: "-606",
      assumption_weighted_pnl: "2394",
      excess_vs_cash: "2394",
      scenarios: outcomes(
        ["-606", "5394"],
        ["394", "6394"],
        ["-0.606", "5.394"],
      ),
    };
    show({
      ...report,
      candidates: [
        { ...cash, sizing_basis: "cash", requested_quantity: null },
        {
          ...stock,
          sizing_basis: "maximum_affordable",
          requested_quantity: null,
        },
        {
          ...call,
          sizing_basis: "requested_quantity",
          requested_quantity: 3,
          base,
          adverse,
        },
      ],
    });
    const table = screen.getByRole("table", {
      name: "Instrument capital and downside comparison",
    });
    const row = within(table)
      .getByRole("rowheader", { name: /Nominated call/ })
      .closest("tr")!;
    expect(within(row).getByText("3 contracts")).toBeVisible();
    expect(within(row).getByText("Investigator-specified")).toBeVisible();
    expect(within(row).getByText("$400.00")).toBeVisible();
    const stockRow = within(table)
      .getByRole("rowheader", { name: /Underlying stock/ })
      .closest("tr")!;
    expect(within(stockRow).getByText("Maximum affordable")).toBeVisible();
    const stress = screen.getByRole("table", {
      name: "Adverse entry cost comparison",
    });
    const stressRow = within(stress)
      .getByRole("rowheader", { name: "Nominated call" })
      .closest("tr")!;
    expect(within(stressRow).getByText("3 contracts")).toBeVisible();
    expect(within(stressRow).getByText("Investigator-specified")).toBeVisible();
    expect(within(stressRow).getByText("$394.00")).toBeVisible();
  });

  it("shows independent hypothetical capital, retained ordering and explicit research/probability assumptions", () => {
    show();
    expect(
      screen.getByRole("region", { name: "Instrument comparison" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Synthetic fixture")).toBeVisible();
    expect(
      screen.getByText(/independently uses the same capital/),
    ).toBeVisible();
    expect(screen.getByText(/15-minute nominal delay/)).toBeVisible();
    const table = screen.getByRole("table", {
      name: "Instrument capital and downside comparison",
    });
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((node) => node.textContent),
    ).toEqual([
      expect.stringContaining("Cash"),
      expect.stringContaining("Underlying stock"),
      expect.stringContaining("Nominated call"),
      expect.stringContaining("Nominated put"),
    ]);
    expect(
      within(table).getByRole("columnheader", {
        name: "Assumption-weighted P&L",
      }),
    ).toBeVisible();
    expect(within(table).getByText("$4,000.00")).toBeVisible();
    expect(screen.getByText(/investigator-supplied assumptions/)).toBeVisible();
    expect(
      screen.getByText(/expiry loss bound is a modeled maximum/),
    ).toBeVisible();
    expect(
      screen.getByText("Inspect saved comparison").closest("details"),
    ).not.toHaveAttribute("open");
  });

  it("withholds weighted values when probability assumptions are missing, even if malformed output contains one", () => {
    show({
      ...report,
      synthetic: false,
      probability_basis: "unweighted_scenarios",
      assumptions: {
        ...assumptions,
        scenarios: scenarios.map((scenario) => ({
          ...scenario,
          probability: null,
        })),
      },
    });
    expect(screen.queryByText("Synthetic fixture")).not.toBeInTheDocument();
    const table = screen.getByRole("table", {
      name: "Instrument capital and downside comparison",
    });
    expect(
      within(table).queryByRole("columnheader", {
        name: "Assumption-weighted P&L",
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("$4,000.00")).not.toBeInTheDocument();
    expect(
      screen.getByText(/No complete probability assumptions/),
    ).toBeVisible();
  });

  it("keeps unavailable candidates and over-budget same-quantity stress visible", () => {
    show();
    const capital = screen.getByRole("table", {
      name: "Instrument capital and downside comparison",
    });
    expect(
      within(capital).getByText(
        "The nominated put is absent from the saved chain.",
      ),
    ).toBeVisible();
    const stress = screen.getByRole("table", {
      name: "Adverse entry cost comparison",
    });
    const row = within(stress)
      .getByRole("rowheader", { name: "Nominated call" })
      .closest("tr")!;
    expect(within(row).getByText("5 contracts")).toBeVisible();
    expect(within(row).getByText("$1,010.00")).toBeVisible();
    expect(within(row).getByText("Over budget")).toBeVisible();
    expect(
      within(row).getByText(/unchanged position exceeds the budget/),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Adverse costs · same quantity" }),
    );
    const outcomes = screen.getByRole("table", {
      name: "Hypothetical expiration scenario outcomes",
    });
    expect(
      within(outcomes).getAllByText("Over budget at this cost"),
    ).toHaveLength(2);
    expect(within(outcomes).getByText("-$199.00")).toBeVisible();
    expect(within(outcomes).getByText("$801.00 terminal")).toBeVisible();
  });

  it("distinguishes retained split-adjusted observations from the assumed share basis and preserves versions", () => {
    show({
      ...report,
      timing: {
        ...(report.timing as JsonObject),
        stock_reference: {
          ...stockReference,
          observation_session: "2026-10-02",
          source_artifact_id: "stock-source-id",
          source_path: "/bars/2/close",
          source: "Synthetic dataset",
          source_price_basis: "split_adjusted",
          share_basis_assumption:
            "Assume the retained share basis is comparable for this hypothetical entry only.",
          corporate_actions_checked: false,
          corporate_actions: [
            { session: "2026-09-30", kind: "split", value: "2" },
          ],
        },
      },
    });
    expect(
      screen.getByText("Dataset close · hypothetical entry"),
    ).toBeVisible();
    expect(
      screen.queryByText("Explicit price assumption"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Split Adjusted")).toBeVisible();
    expect(
      screen.getByText(
        "Assume the retained share basis is comparable for this hypothetical entry only.",
      ),
    ).toBeVisible();
    expect(screen.getByText("Not checked")).toBeVisible();
    expect(
      within(screen.getByText("Observation time").closest("div")!).getByText(
        "Not recorded",
      ),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Retained corporate actions · 1"));
    expect(screen.getByText("2026-09-30 · Split")).toBeVisible();
    fireEvent.click(screen.getByText("Frozen input versions"));
    expect(screen.getByText("chain-id")).toBeVisible();
    expect(screen.getByText("b".repeat(64))).toBeVisible();
    expect(screen.getByText("scenario-source-id")).toBeVisible();
  });

  it("matches a unique scenario across equivalent decimal representations without losing the cash baseline", () => {
    const cashResult = {
      ...(cash.base as JsonObject),
      scenarios: [
        {
          label: "Exponent price",
          underlying_at_expiry: "100",
          probability: "1",
          pnl: "0",
          terminal_capital: "1000",
          return_on_capital: "0",
        },
      ],
    };
    show({
      ...report,
      candidates: [{ ...cash, base: cashResult, adverse: cashResult }],
      assumptions: {
        ...assumptions,
        scenarios: [
          {
            label: "Exponent price",
            underlying_at_expiry: "1E+2",
            probability: "1",
          },
        ],
      },
    });
    const matrix = screen.getByRole("table", {
      name: "Hypothetical expiration scenario outcomes",
    });
    expect(within(matrix).getByText("Underlying $100.00")).toBeVisible();
    expect(within(matrix).getByText("$1,000.00 terminal")).toBeVisible();
    expect(within(matrix).queryByText("Unavailable")).not.toBeInTheDocument();
  });
});
