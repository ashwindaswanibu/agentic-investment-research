import { describe, expect, it } from "vitest";
import {
  parseArtifact,
  parseCapabilities,
  parseCaseDetail,
  parseEvents,
  parsePortfolio,
  parseToolCall,
} from "./contracts";
import {
  artifactFixture,
  capsFixture,
  caseFixture,
  toolFixture,
} from "@/test/fixtures";

describe("API contracts", () => {
  it("retains structured tool output without converting objects to strings", () => {
    expect(parseToolCall(toolFixture).result).toEqual(toolFixture.result);
  });
  it("accepts a full case and rejects a silently renamed tool-call field", () => {
    const detail = {
      ...caseFixture,
      tasks: [],
      artifacts: [artifactFixture],
      tool_calls: [toolFixture],
      events: [],
    };
    expect(parseCaseDetail(detail).artifacts[0].content).toEqual(
      artifactFixture.content,
    );
    expect(() =>
      parseCaseDetail({ ...detail, tool_calls: undefined, toolCalls: [] }),
    ).toThrow("tool calls");
  });
  it("preserves explicit public read-only and provider-unconfigured states", () => {
    const value = parseCapabilities({
      ...capsFixture,
      read_only: true,
      provider: { ...capsFixture.provider, configured: false },
    });
    expect(value.read_only).toBe(true);
    expect(value.provider.configured).toBe(false);
    expect(() =>
      parseCapabilities({ ...capsFixture, read_only: "false" }),
    ).toThrow("read-only");
  });
  it("refuses an unexpected execution mode", () => {
    expect(() =>
      parseCapabilities({ ...capsFixture, execution_mode: "live" }),
    ).toThrow("execution mode");
  });
  it("keeps unvalued equity null, never substituting cash or zero", () => {
    const p = parsePortfolio({
      account_id: "test",
      cash: "150.25",
      equity: null,
      realized_pnl: "0",
      positions: [{ symbol: "TEST", quantity: 1, mark: null }],
      events: [],
      currency: "USD",
      execution_mode: "paper",
      valuation_basis: "Current quotes unavailable",
    });
    expect(p.equity).toBeNull();
    expect(p.cash).toBe("150.25");
    expect(p.positions[0].mark).toBeNull();
  });
  it("rejects non-decimal money instead of presenting an invalid balance", () => {
    expect(() =>
      parsePortfolio({
        account_id: "test",
        cash: "NaN",
        equity: "0",
        realized_pnl: "0",
        positions: [],
        events: [],
        currency: "USD",
        execution_mode: "paper",
      }),
    ).toThrow("cash");
  });
  it("represents an uninitialized account without inventing an account id", () => {
    const value = parsePortfolio({
      account_id: null,
      initialized: false,
      cash: "0",
      equity: "0",
      realized_pnl: "0",
      positions: [],
      events: [],
      currency: "USD",
      execution_mode: "paper",
    });
    expect(value.account_id).toBeNull();
    expect(value.initialized).toBe(false);
  });
  it("preserves review hashes and supports future artifact kinds without accepting malformed names", () => {
    expect(parseArtifact(artifactFixture).sha256).toHaveLength(64);
    expect(
      parseArtifact({ ...artifactFixture, kind: "future_research_record" })
        .kind,
    ).toBe("future_research_record");
    expect(
      parseArtifact({ ...artifactFixture, kind: "clinical_dossier" }).kind,
    ).toBe("clinical_dossier");
    expect(() => parseArtifact({ ...artifactFixture, kind: null })).toThrow(
      "artifact kind",
    );
    expect(() =>
      parseArtifact({ ...artifactFixture, kind: "unbounded kind name" }),
    ).toThrow("artifact kind");
  });
  it("requires the event replay cursor", () => {
    expect(parseEvents({ items: [], cursor: 22 }).cursor).toBe(22);
    expect(() => parseEvents({ items: [] })).toThrow("cursor");
  });
});
