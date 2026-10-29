import {
  ArrowLeftRight,
  BadgePercent,
  BarChart3,
  BookOpenText,
  Briefcase,
  Building2,
  CalendarClock,
  CalendarDays,
  CalendarRange,
  Calculator,
  Coins,
  Columns3,
  FileSpreadsheet,
  FolderKanban,
  Handshake,
  HeartPulse,
  History,
  IdCard,
  Landmark,
  LayoutDashboard,
  ListChecks,
  ListTree,
  NotebookPen,
  PieChart,
  ReceiptText,
  Scale,
  Settings,
  ShieldCheck,
  Tags,
  TrendingUp,
  Truck,
  Upload,
  UserCog,
  UserRound,
  Users,
  UsersRound,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Visible when the user holds any of these permissions. Empty = every signed-in user. */
  anyOf?: string[];
  /** Phase in which the screen ships (docs/architecture.md, Section 18). Undefined = available now. */
  phase?: number;
};

export type NavSection = {
  label: string;
  icon: LucideIcon;
  items: NavItem[];
  /** Items render as top-level links instead of a collapsible group. */
  flat?: boolean;
};

export const NAV: NavSection[] = [
  {
    label: "Home",
    icon: LayoutDashboard,
    flat: true,
    items: [
      { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      { label: "My Salary", href: "/me", icon: Wallet, anyOf: ["salary.read"] },
    ],
  },
  {
    label: "Accounting",
    icon: Calculator,
    items: [
      { label: "Payment Entries", href: "/accounting/payment-entries", icon: ArrowLeftRight, anyOf: ["payments.create", "reports.financial"] },
      { label: "Journal Entries", href: "/accounting/journal-entries", icon: NotebookPen, anyOf: ["journals.post", "reports.financial"] },
      { label: "Chart of Accounts", href: "/accounting/chart-of-accounts", icon: ListTree, anyOf: ["accounts.read"] },
      { label: "General Ledger", href: "/accounting/general-ledger", icon: BookOpenText, anyOf: ["reports.financial"] },
    ],
  },
  {
    label: "Parties",
    icon: Building2,
    items: [
      { label: "Customers", href: "/parties/customers", icon: Handshake, anyOf: ["parties.read"] },
      { label: "Suppliers", href: "/parties/suppliers", icon: Truck, anyOf: ["parties.read"] },
      { label: "Other Parties", href: "/parties/other", icon: UserRound, anyOf: ["parties.read"] },
    ],
  },
  {
    label: "Employees",
    icon: Users,
    items: [
      { label: "Directory", href: "/employees", icon: IdCard, anyOf: ["employees.read"] },
      { label: "Revenue Contributions", href: "/employees/revenue", icon: TrendingUp, anyOf: ["revenue.read"] },
      { label: "Salary", href: "/employees/salary", icon: Coins, anyOf: ["salary.read"] },
      { label: "Salary Formulas", href: "/employees/salary-formulas", icon: BadgePercent, anyOf: ["comp_formulas.read"] },
    ],
  },
  {
    label: "Projects",
    icon: Briefcase,
    items: [
      { label: "All Projects", href: "/projects", icon: FolderKanban, anyOf: ["projects.read"] },
      { label: "Tasks", href: "/projects/tasks", icon: ListChecks, anyOf: ["projects.read"] },
      { label: "Kanban Board", href: "/projects/board", icon: Columns3, anyOf: ["projects.read"] },
      { label: "Gantt Timeline", href: "/projects/timeline", icon: CalendarRange, anyOf: ["projects.read"] },
      { label: "Project Financials", href: "/projects/financials", icon: PieChart, anyOf: ["projects.read_financials"] },
    ],
  },
  {
    label: "Calendar",
    icon: CalendarDays,
    items: [
      { label: "My Calendar", href: "/calendar/me", icon: CalendarDays },
      { label: "Team Calendar", href: "/calendar/team", icon: UsersRound },
      { label: "Company Calendar", href: "/calendar/company", icon: Building2 },
    ],
  },
  {
    label: "Reports",
    icon: BarChart3,
    items: [
      { label: "Financial Statements", href: "/accounting/statements", icon: Scale, anyOf: ["reports.financial"] },
      { label: "Monthly Summary", href: "/reports/monthly", icon: CalendarClock, anyOf: ["reports.financial"] },
      { label: "By Category", href: "/reports/categories", icon: Tags, anyOf: ["reports.financial"] },
      { label: "Customer & Supplier Payments", href: "/reports/parties", icon: ReceiptText, anyOf: ["reports.financial"] },
      { label: "Employee Salary Report", href: "/reports/employees", icon: FileSpreadsheet, anyOf: ["salary.read"] },
    ],
  },
  {
    label: "Settings",
    icon: Settings,
    items: [
      { label: "Company", href: "/settings/company", icon: Building2 },
      { label: "Users", href: "/settings/users", icon: UserCog, anyOf: ["users.manage"] },
      { label: "Roles & Permissions", href: "/settings/roles", icon: ShieldCheck, anyOf: ["roles.manage"] },
      { label: "Custom Categories", href: "/settings/categories", icon: Tags },
      { label: "Currencies & Rates", href: "/settings/currencies", icon: Coins },
      { label: "Payment Accounts", href: "/settings/payment-accounts", icon: Landmark, anyOf: ["payment_accounts.manage", "payments.create"] },
      { label: "Accounting Periods", href: "/settings/periods", icon: CalendarRange, anyOf: ["periods.close", "reports.financial"] },
      { label: "Salary Cycle", href: "/settings/salary-cycle", icon: CalendarClock, anyOf: ["salary.read", "salary.configure_cycle"] },
      { label: "Data Import", href: "/settings/imports", icon: Upload, anyOf: ["imports.manage"] },
      { label: "Audit Log", href: "/settings/audit-logs", icon: History, anyOf: ["audit.read"] },
      { label: "System Checks", href: "/settings/system", icon: HeartPulse, anyOf: ["audit.read"] },
    ],
  },
];

export function canSee(item: NavItem, permissions: Record<string, string>): boolean {
  return !item.anyOf?.length || item.anyOf.some((p) => p in permissions);
}

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV.flatMap((s) => s.items).find((i) => i.href === pathname);
}

/** The single item to highlight: the longest href that is the path or a parent of it (so /employees/salary doesn't also light up /employees). */
export function activeHref(pathname: string): string | undefined {
  let best: string | undefined;
  for (const i of NAV.flatMap((s) => s.items)) {
    if ((pathname === i.href || pathname.startsWith(`${i.href}/`)) && (!best || i.href.length > best.length)) best = i.href;
  }
  return best;
}
