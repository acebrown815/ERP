import { describe, expect, it } from "vitest";

import { rankBetween } from "./rank";

describe("rankBetween", () => {
  it("matches the server and stays strictly between", () => {
    expect(rankBetween(null, null)).toBe("i"); // same as tasks/rank.py first()
    const a = rankBetween(null, null);
    const b = rankBetween(a, null);
    let hi = b;
    for (let n = 0; n < 40; n++) {
      const m = rankBetween(a, hi);
      expect(a < m && m < hi).toBe(true);
      expect(m.endsWith("0")).toBe(false);
      hi = m;
    }
    expect(() => rankBetween(b, a)).toThrow();
  });
});
