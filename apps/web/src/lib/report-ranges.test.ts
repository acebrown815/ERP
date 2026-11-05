import { describe, expect, it } from "vitest";

import { ALL_TIME_FROM, matchPreset, rangePresets } from "./report-ranges";

const period = (start_date: string, end_date: string, extra: { is_current?: boolean; is_future?: boolean } = {}) => ({
  start_date,
  end_date,
  is_current: false,
  is_future: false,
  ...extra,
});

// Newest first, as the API returns them, on a cycle starting on the 25th.
const PERIODS = [
  period("2026-11-25", "2026-12-24", { is_future: true }),
  period("2026-10-25", "2026-11-24", { is_current: true }),
  period("2026-09-25", "2026-10-24"),
  period("2026-08-25", "2026-09-24"),
  period("2026-07-25", "2026-08-24"),
  period("2026-06-25", "2026-07-24"),
  period("2026-05-25", "2026-06-24"),
  period("2026-04-25", "2026-05-24"),
];
const TODAY = new Date(2026, 10, 10);
const range = (key: string, periods = PERIODS) => rangePresets(periods, TODAY).find((p) => p.key === key)?.range;

describe("rangePresets", () => {
  it("follows the salary periods, not calendar months", () => {
    expect(range("this_month")).toEqual({ from: "2026-10-25", to: "2026-11-24" });
    expect(range("last_month")).toEqual({ from: "2026-09-25", to: "2026-10-24" });
  });

  it("counts the current period in the last 3 and 6 months", () => {
    expect(range("last_3")).toEqual({ from: "2026-08-25", to: "2026-11-24" });
    expect(range("last_6")).toEqual({ from: "2026-05-25", to: "2026-11-24" });
  });

  it("offers the whole year and everything to date", () => {
    expect(range("this_year")).toEqual({ from: "2026-01-01", to: "2026-12-31" });
    expect(range("all_time")).toEqual({ from: ALL_TIME_FROM, to: "2026-11-24" });
  });

  it("offers a range only once there are enough periods for it", () => {
    const young = PERIODS.slice(0, 3);
    expect(rangePresets(young, TODAY).map((p) => p.key)).toEqual(["this_month", "last_month", "this_year", "all_time"]);
  });

  it("falls back to the calendar month without periods", () => {
    expect(rangePresets([], TODAY).map((p) => p.key)).toEqual(["this_month", "this_year", "all_time"]);
    expect(range("this_month", [])).toEqual({ from: "2026-11-01", to: "2026-11-30" });
    expect(range("all_time", [])).toEqual({ from: ALL_TIME_FROM, to: "2026-11-30" });
  });
});

describe("matchPreset", () => {
  const presets = rangePresets(PERIODS, TODAY);

  it("recognises a preset from its dates", () => {
    expect(matchPreset(presets, { from: "2026-08-25", to: "2026-11-24" })).toBe("last_3");
  });

  it("treats anything else as custom", () => {
    expect(matchPreset(presets, { from: "2026-08-26", to: "2026-11-24" })).toBeUndefined();
  });
});
