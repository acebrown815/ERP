import { describe, expect, it } from "vitest";

import { pageItems, parsePageInput } from "./pagination";

describe("pageItems", () => {
  it("shows every page when there are few", () => {
    expect(pageItems(1, 1)).toEqual([1]);
    expect(pageItems(2, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("collapses long runs into gaps around the current page", () => {
    expect(pageItems(1, 157)).toEqual([1, 2, "gap", 157]);
    expect(pageItems(50, 157)).toEqual([1, "gap", 49, 50, 51, "gap", 157]);
    expect(pageItems(157, 157)).toEqual([1, "gap", 156, 157]);
  });

  it("fills a gap of one page instead of hiding it", () => {
    expect(pageItems(4, 157)).toEqual([1, 2, 3, 4, 5, "gap", 157]);
    expect(pageItems(154, 157)).toEqual([1, "gap", 153, 154, 155, 156, 157]);
  });
});

describe("parsePageInput", () => {
  it("accepts whole numbers and keeps them in range", () => {
    expect(parsePageInput(" 12 ", 157)).toBe(12);
    expect(parsePageInput("0", 157)).toBe(1);
    expect(parsePageInput("999", 157)).toBe(157);
  });

  it("rejects anything else", () => {
    expect(parsePageInput("", 157)).toBeNull();
    expect(parsePageInput("1.5", 157)).toBeNull();
    expect(parsePageInput("-3", 157)).toBeNull();
    expect(parsePageInput("abc", 157)).toBeNull();
  });
});
