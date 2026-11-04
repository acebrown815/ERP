import { describe, expect, it } from "vitest";

import { dashboardScope } from "./dashboard-scope";

const bidder = { employee_id: "e1", profile_names: ["Devin"] };
const noNames = { employee_id: "e2", profile_names: [] };

describe("dashboardScope", () => {
  it("shows a bidder their own numbers, whatever their roles allow", () => {
    expect(dashboardScope(bidder, false)).toEqual({ team: false, employeeId: "e1" });
    expect(dashboardScope(bidder, true)).toEqual({ team: false, employeeId: "e1" });
  });

  it("shows the team to a manager who doesn't bid", () => {
    expect(dashboardScope(undefined, true)).toEqual({ team: true });
    expect(dashboardScope(noNames, true)).toEqual({ team: true });
  });

  it("never shows the team to someone limited to their own bids", () => {
    expect(dashboardScope(undefined, false)).toEqual({ team: false });
    expect(dashboardScope(noNames, false)).toEqual({ team: false });
  });
});
