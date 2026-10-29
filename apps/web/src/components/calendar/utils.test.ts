import { describe, expect, it } from "vitest";

import { describeRRule, fromRRule, monthGrid, toRRule, weekStart } from "./utils";

describe("calendar utils", () => {
  it("round-trips repeat rules", () => {
    const rule = toRRule({ freq: "WEEKLY", byday: ["MO", "WE"], end: "until", until: "2027-01-31", count: "" });
    expect(rule).toBe("FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20270131");
    expect(fromRRule(rule)).toEqual({ freq: "WEEKLY", byday: ["MO", "WE"], end: "until", until: "2027-01-31", count: "" });
    expect(toRRule({ freq: "", byday: [], end: "never", until: "", count: "" })).toBeNull();
    expect(describeRRule("FREQ=MONTHLY;COUNT=6")).toBe("Monthly, 6 times");
  });
  it("builds Monday-first month grids", () => {
    expect(weekStart("2026-11-12")).toBe("2026-11-09");
    const grid = monthGrid("2026-11-12");
    expect(grid).toHaveLength(42);
    expect(grid[0]).toBe("2026-10-26");
  });
});
