import { describe, expect, it } from "vitest";

import { canSee, hireMayOpen, NAV } from "./nav";

const HIRE_PERMISSIONS = {
  "projects.read": "project",
  "tasks.manage": "project",
  "tasks.update_own": "project",
  "payments.read_own": "all",
};

const visible = (permissions: Record<string, string>, isHire: boolean) =>
  NAV.flatMap((s) => s.items)
    .filter((i) => canSee(i, permissions, isHire))
    .map((i) => i.href);

describe("screens a hired manager can open", () => {
  it("allows their work, pay and calendar", () => {
    for (const path of ["/dashboard", "/projects", "/projects/abc", "/projects/tasks", "/projects/board", "/accounting/payment-entries", "/accounting/payment-entries/abc", "/calendar/me"]) {
      expect(hireMayOpen(path), path).toBe(true);
    }
  });

  it("sends them away from everything else", () => {
    for (const path of ["/settings/company", "/employees", "/employees/abc", "/me", "/reports/monthly", "/bidding", "/parties/customers", "/calendar/team", "/calendar/company", "/projects/financials", "/accounting/payment-entries/new", "/accounting/chart-of-accounts", "/projectsx"]) {
      expect(hireMayOpen(path), path).toBe(false);
    }
  });
});

describe("menu for a hired manager", () => {
  it("shows only their work, pay and calendar", () => {
    expect(visible(HIRE_PERMISSIONS, true).sort()).toEqual(
      [
        "/accounting/payment-entries",
        "/calendar/me",
        "/dashboard",
        "/projects",
        "/projects/board",
        "/projects/tasks",
        "/projects/timeline",
      ].sort(),
    );
  });

  it("leaves the open pages in place for everyone else", () => {
    const others = visible({}, false);
    expect(others).toContain("/settings/company");
    expect(others).toContain("/calendar/team");
  });

  it("shows the monitoring page to anyone allowed to read it", () => {
    expect(visible({ "hired_managers.read": "own" }, false)).toContain("/employees/hired-managers");
    expect(visible({}, false)).not.toContain("/employees/hired-managers");
  });
});
