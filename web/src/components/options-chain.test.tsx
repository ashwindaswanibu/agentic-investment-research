// Synthetic source records for interface tests, never market observations.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseArtifact, type JsonObject } from "@/lib/contracts";
import { artifactFixture } from "@/test/fixtures";
import { ArtifactContent } from "./artifacts";

const call: JsonObject = {
  symbol: "TEST261016C00100000",
  underlying: "TEST",
  option_type: "call",
  root_symbol: "TEST",
  strike: "100.000",
  expiration: "2026-10-16",
  contract_size: 100,
  contract_status: "unverified",
  bid: "2.125",
  ask: "2.150",
  bid_size: 12,
  ask_size: 9,
  bid_at: "2026-10-05T14:00:00+00:00",
  ask_at: "2026-10-05T14:00:01+00:00",
  bid_age_seconds: 900,
  ask_age_seconds: 899,
  size_unit: "provider_reported_unverified",
  open_interest: 210,
  volume: 0,
  issues: ["contract_deliverable_unverified"],
};
const put: JsonObject = {
  ...call,
  symbol: "TEST261016P00105000",
  option_type: "put",
  strike: "105.000",
  bid: null,
  bid_at: null,
  bid_age_seconds: null,
  bid_size: null,
  ask: "0.00",
  ask_size: 0,
  open_interest: null,
  issues: [
    "bid_missing",
    "bid_timestamp_missing",
    "contract_deliverable_unverified",
  ],
};
const snapshot: JsonObject = {
  schema_version: "options_chain.v1",
  provider: "tradier",
  feed: "sandbox",
  delay_seconds: 900,
  execution_eligible: false,
  underlying: "TEST",
  expiration: "2026-10-16",
  acquisition_started_at: "2026-10-05T14:14:59+00:00",
  received_at: "2026-10-05T14:15:00+00:00",
  contracts: [put, call],
  issues: ["delayed_research_only", "market_coverage_unverified"],
  research_purpose: "Inspect source coverage for a research hypothesis.",
};
function artifact(
  content: JsonObject = snapshot,
  metadata: JsonObject = { synthetic: true },
) {
  return parseArtifact({
    ...artifactFixture,
    kind: "options_chain",
    content,
    metadata,
  });
}

describe("saved options-chain inspector", () => {
  it("routes the artifact with research limitations and synthetic provenance", () => {
    render(<ArtifactContent artifact={artifact()} />);
    expect(
      screen.getByRole("region", { name: "Options chain snapshot" }),
    ).toBeInTheDocument();
    expect(screen.getByText("15-minute delayed · Research only")).toBeVisible();
    expect(screen.getByText("Synthetic fixture")).toBeVisible();
    expect(screen.getByText(snapshot.research_purpose as string)).toBeVisible();
    expect(screen.getByText(/not eligible for execution/)).toBeVisible();
    expect(screen.queryByText(/midpoint|greeks/i)).not.toBeInTheDocument();
  });

  it("keeps bid and ask source times separate from acquisition and receipt", () => {
    render(<ArtifactContent artifact={artifact()} />);
    expect(screen.getByText("2026-10-05 14:14:59 UTC")).toBeVisible();
    expect(screen.getByText("2026-10-05 14:15:00 UTC")).toBeVisible();
    const table = screen.getByRole("table", {
      name: "Recorded option contracts",
    });
    expect(within(table).getByText("14:00:00 UTC")).toBeVisible();
    expect(within(table).queryByText(/14:15:00/)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: `Inspect ${put.symbol}` }),
    );
    const details = screen.getByText("Bid source timestamp").closest("div")!;
    expect(within(details).getByText("Not recorded")).toBeVisible();
    expect(screen.getByText("No bid price was recorded.")).toBeVisible();
    expect(screen.getByText(/unit is unverified/)).toBeVisible();
    expect(
      screen.getByText(/contract deliverable has not been verified/),
    ).toBeVisible();
  });

  it("preserves quote precision, zero and missing values without invented prices", () => {
    render(<ArtifactContent artifact={artifact()} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("2.125")).toBeVisible();
    expect(within(table).getByText("2.150")).toBeVisible();
    expect(within(table).getByText("0.00")).toBeVisible();
    expect(within(table).getByText("Size 0")).toBeVisible();
    expect(within(table).getByText("bid unavailable")).toBeInTheDocument();
    const headers = within(table).getAllByRole("rowheader");
    expect(headers[0]).toHaveTextContent(call.symbol as string);
    expect(headers[1]).toHaveTextContent(put.symbol as string);
  });

  it("exposes a different source date without requiring hover or record expansion", () => {
    render(
      <ArtifactContent
        artifact={artifact({
          ...snapshot,
          contracts: [{ ...call, bid_at: "2026-10-02T14:00:00+00:00" }],
        })}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("2026-10-02")).toBeVisible();
    expect(within(table).getByText("14:00:00 UTC")).toBeVisible();
    expect(
      screen.getByText(/nominal delay does not guarantee quote age/),
    ).toBeVisible();
  });

  it("retains a flagged negative quote as an observation rather than treating it as missing", () => {
    render(
      <ArtifactContent
        artifact={artifact({
          ...snapshot,
          contracts: [{ ...call, bid: "-1.25", issues: ["bid_nonpositive"] }],
        })}
      />,
    );
    expect(within(screen.getByRole("table")).getByText("-1.25")).toBeVisible();
    expect(screen.getByText("Nonpositive quote")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: `Inspect ${call.symbol}` }),
    );
    expect(screen.getByText(/bid is zero or negative/)).toBeVisible();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter data issues" }),
      { target: { value: "missing_quote" } },
    );
    expect(screen.getByText("No contracts match these filters")).toBeVisible();
  });

  it("filters recorded rows by side, strike and data condition and recovers empty results", () => {
    render(<ArtifactContent artifact={artifact()} />);
    fireEvent.click(screen.getByRole("button", { name: /Calls 1/ }));
    expect(screen.getByRole("button", { name: /Calls 1/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 contracts");
    expect(
      within(screen.getByRole("table")).queryByText(put.symbol as string),
    ).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter data issues" }),
      { target: { value: "missing_quote" } },
    );
    expect(screen.getByText("No contracts match these filters")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search symbol or strike" }),
      { target: { value: "105" } },
    );
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 contracts");
    expect(
      within(screen.getByRole("table")).getByText(put.symbol as string),
    ).toBeVisible();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search symbol or strike" }),
      { target: { value: "" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /Puts 1/ }));
    expect(
      within(screen.getByRole("table")).queryByText(call.symbol as string),
    ).not.toBeInTheDocument();
  });

  it("makes crossed and unsupported records discoverable without marking them tradable", () => {
    render(
      <ArtifactContent
        artifact={artifact({
          ...snapshot,
          contracts: [
            {
              ...call,
              bid: "2.50",
              contract_size: 10,
              contract_status: "unsupported",
              issues: [
                "crossed_quote",
                "nonstandard_contract_size",
                "adjusted_root_unsupported",
              ],
            },
          ],
        })}
      />,
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter data issues" }),
      { target: { value: "crossed" } },
    );
    expect(screen.getByRole("status")).toHaveTextContent("1 of 1 contracts");
    expect(screen.getByText("Unsupported")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: `Inspect ${call.symbol}` }),
    );
    expect(screen.getByText(/recorded bid exceeds the ask/)).toBeVisible();
    expect(
      screen.getByText(/adjusted contract root is unsupported/),
    ).toBeVisible();
    expect(
      within(
        screen.getByText("Reported contract size").closest("div")!,
      ).getByText("10"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: `Inspect ${call.symbol}` }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("shows empty and malformed records honestly and retains the raw data", () => {
    const first = render(
      <ArtifactContent
        artifact={artifact({
          ...snapshot,
          contracts: [],
          issues: ["empty_chain"],
        })}
      />,
    );
    expect(screen.getByText("No contract records")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("Inspect saved options data")).toBeVisible();
    first.unmount();
    render(
      <ArtifactContent
        artifact={artifact({
          ...snapshot,
          contracts: [null, "bad source row", call],
        })}
      />,
    );
    expect(screen.getByText(/2 unreadable contract records/)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("1 of 1 contracts");
  });

  it("marks content-level fixtures but does not mislabel real snapshots", () => {
    const first = render(<ArtifactContent artifact={artifact(snapshot, {})} />);
    expect(screen.queryByText("Synthetic fixture")).not.toBeInTheDocument();
    first.unmount();
    render(
      <ArtifactContent
        artifact={artifact({ ...snapshot, synthetic: true }, {})}
      />,
    );
    expect(screen.getByText("Synthetic fixture")).toBeVisible();
  });

  it("paginates the same saved record and resets paging when filters change", () => {
    const contracts = Array.from({ length: 43 }, (_, index) => ({
      ...call,
      symbol: `TEST-C-${index}`,
      strike: `${100 + index}`,
    }));
    render(<ArtifactContent artifact={artifact({ ...snapshot, contracts })} />);
    expect(
      within(screen.getByRole("table")).getAllByRole("rowheader"),
    ).toHaveLength(40);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 2")).toBeVisible();
    expect(
      within(screen.getByRole("table")).getAllByRole("rowheader"),
    ).toHaveLength(3);
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search symbol or strike" }),
      { target: { value: "TEST-C-0" } },
    );
    expect(
      within(screen.getByRole("table")).getByText("TEST-C-0"),
    ).toBeVisible();
    expect(
      screen.queryByRole("navigation", { name: "Contract pages" }),
    ).not.toBeInTheDocument();
  });

  it("escapes untrusted source text and falls back for unknown schema versions", () => {
    const { container } = render(
      <ArtifactContent
        artifact={artifact({
          ...snapshot,
          schema_version: "options_chain.v99",
          research_purpose: "<script>alert(1)</script>",
        })}
      />,
    );
    expect(
      screen.getByText(/supported options-chain snapshot is unavailable/),
    ).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(
      screen.getByText("Inspect saved options data").closest("details"),
    ).toHaveAttribute("open");
  });
});
