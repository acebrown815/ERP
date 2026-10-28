import { describe, expect, it } from "vitest";

import { decimals, formatAmount, formatMoney, sign, sum } from "./money";

describe("formatAmount", () => {
  it("groups thousands and pads decimals", () => {
    expect(formatAmount("10000.0000")).toBe("10,000.00");
    expect(formatAmount("1234567.5")).toBe("1,234,567.50");
    expect(formatAmount("0")).toBe("0.00");
  });

  it("rounds half up on the string, carrying across digits", () => {
    expect(formatAmount("626.666")).toBe("626.67");
    expect(formatAmount("9.995")).toBe("10.00");
    expect(formatAmount("999.999")).toBe("1,000.00");
  });

  it("keeps negatives and drops a negative zero", () => {
    expect(formatAmount("-2.50")).toBe("-2.50");
    expect(formatAmount("-0.001")).toBe("0.00");
  });

  it("handles crypto precision without floats", () => {
    expect(formatAmount("0.123456789012345678", 18)).toBe("0.123456789012345678");
    expect(formatAmount("1000.000000", 6)).toBe("1,000.000000");
  });

  it("formats with currency", () => {
    expect(formatMoney("999", "USD")).toBe("999.00 USD");
    expect(formatMoney(null, "USD")).toBe("—");
  });
});

describe("helpers", () => {
  it("counts decimals", () => {
    expect(decimals("10.123")).toBe(3);
    expect(decimals("10")).toBe(0);
  });

  it("sums exactly", () => {
    expect(sum(["0.1", "0.2"])).toBe("0.3");
    expect(sum(["6000.0000", "4000.0000"])).toBe("10000");
    expect(sum(["-2.5", "1"])).toBe("-1.5");
  });

  it("knows the sign", () => {
    expect(sign("0.00")).toBe(0);
    expect(sign("-1")).toBe(-1);
    expect(sign("3")).toBe(1);
  });
});
