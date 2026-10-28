import { describe, expect, it } from "vitest";

import { formatPeriodRange, salaryPeriodFor, upcomingPeriods } from "./salary-cycle";

const iso = (d: Date) => d.toISOString().slice(0, 10);

describe("salaryPeriodFor", () => {
  it("uses 25th-24th when the cycle starts on the 25th", () => {
    const p = salaryPeriodFor(2026, 10, 25); // Nov 2026
    expect(p.label).toBe("Nov 2026");
    expect([iso(p.start), iso(p.end)]).toEqual(["2026-10-25", "2026-11-24"]);
  });

  it("crosses the year boundary", () => {
    const p = salaryPeriodFor(2027, 0, 25); // Jan 2027
    expect([iso(p.start), iso(p.end)]).toEqual(["2026-12-25", "2027-01-24"]);
  });

  it("is the calendar month when the cycle starts on the 1st (leap year)", () => {
    const p = salaryPeriodFor(2028, 1, 1);
    expect([iso(p.start), iso(p.end)]).toEqual(["2028-02-01", "2028-02-29"]);
  });

  it("rejects days that not every month has", () => {
    expect(() => salaryPeriodFor(2026, 1, 29)).toThrow(RangeError);
  });

  it("produces contiguous periods for every start day", () => {
    for (let day = 1; day <= 28; day++) {
      const periods = Array.from({ length: 14 }, (_, i) => salaryPeriodFor(2026, i, day));
      for (let i = 1; i < periods.length; i++) {
        const gap = periods[i]!.start.getTime() - periods[i - 1]!.end.getTime();
        expect(gap).toBe(86_400_000);
      }
    }
  });
});

describe("upcomingPeriods", () => {
  it("puts Nov 24 in Nov and Nov 25 in Dec for a 25th cycle", () => {
    expect(upcomingPeriods(new Date(Date.UTC(2026, 10, 24)), 25, 1)[0]!.label).toBe("Nov 2026");
    expect(upcomingPeriods(new Date(Date.UTC(2026, 10, 25)), 25, 1)[0]!.label).toBe("Dec 2026");
  });

  it("formats a range", () => {
    expect(formatPeriodRange(salaryPeriodFor(2026, 10, 25))).toBe("Oct 25 – Nov 24");
  });
});
