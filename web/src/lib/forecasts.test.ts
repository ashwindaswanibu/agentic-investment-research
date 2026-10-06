import { describe, expect, it } from "vitest";
import { forecastFixture, resolutionFixture } from "@/test/forecast-fixtures";
import {
  localDateToISO,
  parseForecasts,
  sortForecasts,
  utcDate,
} from "./forecasts";

describe("forecast contracts", () => {
  it("retains every status and orders due records first without changing input", () => {
    const records = parseForecasts({
      items: [
        forecastFixture("abstained", "abstained"),
        forecastFixture("pending", "pending"),
        forecastFixture("due", "due"),
        forecastFixture("unresolvable", "unresolvable"),
      ],
    });
    expect(sortForecasts(records).map((r) => r.assessment.status)).toEqual([
      "due",
      "pending",
      "abstained",
      "unresolvable",
    ]);
    expect(records[0].assessment.status).toBe("abstained");
    expect(records[0].content.probability).toBeNull();
  });
  it("preserves zero probability, perfect Brier scores, and negative baseline improvement", () => {
    const record = forecastFixture("zero", "resolved");
    record.forecast.content.probability = 0;
    record.assessment = {
      status: "resolved",
      scored: true,
      brier: 0,
      baseline_brier: 0,
      improvement: 0,
    };
    expect(parseForecasts({ items: [record] })[0].assessment.brier).toBe(0);
    record.assessment = {
      status: "resolved",
      scored: true,
      brier: 0.8,
      baseline_brier: 0.3,
      improvement: -0.5,
    };
    expect(parseForecasts({ items: [record] })[0].assessment.improvement).toBe(
      -0.5,
    );
  });
  it("requires the current judgment to exist in immutable history", () => {
    const record = forecastFixture();
    record.latest_resolution = resolutionFixture();
    expect(() => parseForecasts({ items: [record] })).toThrow(
      "latest resolution reference",
    );
    record.resolutions = [record.latest_resolution];
    expect(parseForecasts({ items: [record] })[0].resolutions).toHaveLength(1);
  });
  it.each([
    (record: ReturnType<typeof forecastFixture>) => {
      record.forecast.content.probability = 1.2;
    },
    (record: ReturnType<typeof forecastFixture>) => {
      record.forecast.content.opens_at = "not a date";
    },
    (record: ReturnType<typeof forecastFixture>) => {
      record.assessment.scored = true;
    },
    (record: ReturnType<typeof forecastFixture>) => {
      record.assessment.improvement = Infinity;
    },
    (record: ReturnType<typeof forecastFixture>) => {
      record.forecast.content.status = "abstain";
    },
  ])("rejects an invalid saved record", (change) => {
    const record = forecastFixture();
    change(record);
    expect(() => parseForecasts({ items: [record] })).toThrow();
  });
  it("converts browser-local input to an explicit UTC instant", () => {
    const local = "2099-02-01T09:30";
    expect(localDateToISO(local)).toBe(
      new Date(2099, 1, 1, 9, 30).toISOString(),
    );
    expect(utcDate("2099-02-01T09:30:00-05:00")).toBe(
      "2099-02-01 14:30:00 UTC",
    );
    expect(() => localDateToISO("")).toThrow("valid event window");
  });
});
