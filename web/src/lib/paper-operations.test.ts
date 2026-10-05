import { describe, expect, it } from "vitest";
import {
  EMPTY_MANDATE,
  mandatePayload,
  parseMandate,
  parsePaperOperations,
} from "./paper-operations";
import {
  mandateFixture,
  mandateValues,
  operationsFixture,
} from "@/test/paper-fixtures";

describe("explicit paper operations contract", () => {
  it("preserves decimal limits and distinguishes missing valuations from zero", () => {
    const result = parsePaperOperations({
      ...operationsFixture,
      latest_observation: {
        equity: null,
        cash: "123.45",
        missing_symbols: ["TEST"],
      },
      performance: {
        equity_series: [{ equity: null }],
        daily: [{ net_pnl: null }],
        latest: { equity: null },
        calendar_coverage: {
          complete: false,
          start: "2026-09-30",
          end: "2026-10-05",
          verified_at: "2026-10-05T16:00:00Z",
          reason: "CALENDAR_COVERAGE_INCOMPLETE",
        },
      },
    });
    expect(result.mandate?.payload.policy.max_order_notional).toBe("1250.50");
    expect(result.latest_observation?.equity).toBeNull();
    expect(result.performance.daily[0].net_pnl).toBeNull();
    expect(result.performance.calendar_coverage).toEqual({
      complete: false,
      start: "2026-09-30",
      end: "2026-10-05",
      verified_at: "2026-10-05T16:00:00Z",
      reason: "CALENDAR_COVERAGE_INCOMPLETE",
    });
  });
  it("requires an explicit mode and compare-and-swap version", () => {
    expect(() =>
      parsePaperOperations({
        ...operationsFixture,
        control: { mode: "live", version: 1, mandate_id: null },
      }),
    ).toThrow("mode");
    expect(() =>
      parsePaperOperations({
        ...operationsFixture,
        control: { mode: "active", mandate_id: null },
      }),
    ).toThrow("version");
  });
  it("starts with every input blank and supplies no silent risk defaults", () => {
    expect(Object.values(EMPTY_MANDATE).every((value) => value === "")).toBe(
      true,
    );
    expect(() => mandatePayload(EMPTY_MANDATE)).toThrow(
      "Complete every mandate field",
    );
    expect(() => mandatePayload({ ...mandateValues, fee_bps: "" })).toThrow(
      "Complete every mandate field",
    );
  });
  it("converts explicit local expiry to UTC and preserves exact decimal strings", () => {
    const payload = mandatePayload(mandateValues);
    expect(payload.expires_at).toBe(
      new Date(mandateValues.expires_at).toISOString(),
    );
    expect(payload.policy.fee_bps).toBe("1.5");
    expect(payload.max_drawdown_amount).toBe("125.00");
    expect(payload.max_open_orders).toBe(3);
  });
  it("rejects duplicate symbols, stale expiry, fractions in integer fields and stale quote limits", () => {
    expect(() =>
      mandatePayload({ ...mandateValues, symbols: "TEST,test" }),
    ).toThrow("distinct");
    expect(() =>
      mandatePayload({ ...mandateValues, expires_at: "2001-01-01T12:00" }),
    ).toThrow("future");
    expect(() =>
      mandatePayload({ ...mandateValues, max_open_orders: "1.5" }),
    ).toThrow("whole number");
    expect(() =>
      mandatePayload({ ...mandateValues, max_quote_age_seconds: "61" }),
    ).toThrow("1 to 60");
    expect(() =>
      parseMandate({
        ...mandateFixture,
        payload: {
          ...mandateFixture.payload,
          policy: {
            ...mandateFixture.payload.policy,
            max_quote_age_seconds: 61,
          },
        },
      }),
    ).toThrow("quote age");
  });
});
