import {
  BarChart3,
  Briefcase,
  Building2,
  CalendarDays,
  Calculator,
  LayoutDashboard,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  /** Visible when the user holds any of these permissions. Empty = every signed-in user. */
  anyOf?: string[];
  /** Phase in which the screen ships (docs/architecture.md, Section 18). Undefined = available now. */
  phase?: number;
};

export type NavSection = {
  label: string;
  icon: LucideIcon;
  items: NavItem[];
};

export const NAV: NavSection[] = [
  {
    label: "Dashboard",
    icon: LayoutDashboard,
    items: [{ label: "Overview", href: "/dashboard" }],
  },
  {
    label: "Accounting",
    icon: Calculator,
    items: [
      { label: "Chart of Accounts", href: "/accounting/chart-of-accounts", anyOf: ["accounts.read"], phase: 2 },
      { label: "Payment Entries", href: "/accounting/payment-entries", anyOf: ["payments.create"], phase: 2 },
      { label: "Journal Entries", href: "/accounting/journal-entries", anyOf: ["journals.post"], phase: 2 },
      { label: "General Ledger", href: "/accounting/general-ledger", anyOf: ["reports.financial"], phase: 2 },
      { label: "Income & Expenses", href: "/accounting/income-expenses", anyOf: ["reports.financial"], phase: 2 },
    ],
  },
  {
    label: "Parties",
    icon: Building2,
    items: [
      { label: "Customers", href: "/parties/customers", anyOf: ["parties.read"], phase: 2 },
      { label: "Suppliers", href: "/parties/suppliers", anyOf: ["parties.read"], phase: 2 },
      { label: "Other Parties", href: "/parties/other", anyOf: ["parties.read"], phase: 2 },
    ],
  },
  {
    label: "Employees",
    icon: Users,
    items: [
      { label: "Directory", href: "/employees", anyOf: ["employees.read"], phase: 2 },
      { label: "Revenue Contributions", href: "/employees/revenue", anyOf: ["revenue.read"], phase: 3 },
      { label: "Salary Formulas", href: "/employees/salary-formulas", anyOf: ["comp_formulas.read"], phase: 3 },
      { label: "Salary", href: "/employees/salary", anyOf: ["salary.read"], phase: 3 },
    ],
  },
  {
    label: "Projects",
    icon: Briefcase,
    items: [
      { label: "All Projects", href: "/projects", anyOf: ["projects.read"], phase: 4 },
      { label: "Tasks", href: "/projects/tasks", anyOf: ["projects.read"], phase: 4 },
      { label: "Kanban Board", href: "/projects/board", anyOf: ["projects.read"], phase: 4 },
      { label: "Gantt Timeline", href: "/projects/timeline", anyOf: ["projects.read"], phase: 4 },
      { label: "Project Financials", href: "/projects/financials", anyOf: ["projects.read_financials"], phase: 4 },
    ],
  },
  {
    label: "Calendar",
    icon: CalendarDays,
    items: [
      { label: "My Calendar", href: "/calendar/me", phase: 5 },
      { label: "Team Calendar", href: "/calendar/team", phase: 5 },
      { label: "Company Calendar", href: "/calendar/company", phase: 5 },
    ],
  },
  {
    label: "Reports",
    icon: BarChart3,
    items: [
      { label: "Financial Reports", href: "/reports/financial", anyOf: ["reports.financial"], phase: 5 },
      { label: "Employee Reports", href: "/reports/employees", anyOf: ["revenue.read"], phase: 5 },
      { label: "Project Reports", href: "/reports/projects", anyOf: ["projects.read"], phase: 5 },
    ],
  },
  {
    label: "Settings",
    icon: Settings,
    items: [
      { label: "Company", href: "/settings/company" },
      { label: "Users", href: "/settings/users", anyOf: ["users.manage"] },
      { label: "Roles & Permissions", href: "/settings/roles", anyOf: ["roles.manage"] },
      { label: "Custom Categories", href: "/settings/categories" },
      { label: "Currencies & Rates", href: "/settings/currencies" },
      { label: "Audit Log", href: "/settings/audit-logs", anyOf: ["audit.read"] },
    ],
  },
];

export function canSee(item: NavItem, permissions: Record<string, string>): boolean {
  return !item.anyOf?.length || item.anyOf.some((p) => p in permissions);
}

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV.flatMap((s) => s.items).find((i) => i.href === pathname);
}
