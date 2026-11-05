import {
  ArrowLeftRight,
  BadgePercent,
  Banknote,
  BarChart3,
  BookOpenText,
  Briefcase,
  Building2,
  CalendarClock,
  CalendarCheck,
  CalendarDays,
  CalendarRange,
  Calculator,
  Coins,
  DatabaseBackup,
  Columns3,
  FileSpreadsheet,
  FolderKanban,
  Gauge,
  Handshake,
  HeartPulse,
  History,
  IdCard,
  Landmark,
  LayoutDashboard,
  LineChart,
  ListChecks,
  ListTree,
  NotebookPen,
  PieChart,
  ReceiptText,
  Scale,
  Search,
  Send,
  Sheet,
  Settings,
  ShieldCheck,
  Tags,
  Target,
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
  /** Visible only with company-wide ("all") scope on this permission, e.g. team-level bidding reports. */
  allScope?: string;
  /** Phase in which the screen ships (docs/architecture.md, Section 18). Undefined = available now. */
  phase?: number;
  /** Not in a hired manager's menu, for pages open to every signed-in user that don't concern them. */
  hideForHire?: boolean;
  /** The label a hired manager sees, where the usual one would mislead. */
  hireLabel?: string;
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
      // Employees see the payments about themselves (read-only).
      { label: "Payment Entries", href: "/accounting/payment-entries", icon: ArrowLeftRight, hireLabel: "Payments", anyOf: ["payments.create", "reports.financial", "salary.read", "revenue.read", "payments.read_own"] },
      { label: "Journal Entries", href: "/accounting/journal-entries", icon: NotebookPen, anyOf: ["journals.post", "reports.financial"] },
      { label: "Chart of Accounts", href: "/accounting/chart-of-accounts", icon: ListTree, anyOf: ["accounts.read"] },
      { label: "General Ledger", href: "/accounting/general-ledger", icon: BookOpenText, anyOf: ["reports.financial"] },
    ],
  },
  {
    label: "Bidding",
    icon: Target,
    items: [
      { label: "My Bidding", href: "/bidding/me", icon: Target, anyOf: ["bidding.read"] },
      { label: "Team Overview", href: "/bidding", icon: Gauge, allScope: "bidding.read" },
      { label: "Daily Report", href: "/bidding/daily", icon: CalendarCheck, allScope: "bidding.read" },
      { label: "All Bids", href: "/bidding/bids", icon: Send, allScope: "bidding.read" },
      { label: "Job List", href: "/bidding/jobs", icon: Search, anyOf: ["bidding.read"] },
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
      { label: "Directory", href: "/employees", icon: IdCard, anyOf: ["employees.read"], hideForHire: true },
      { label: "Hired Managers", href: "/employees/hired-managers", icon: UserRound, anyOf: ["hired_managers.read"] },
      { label: "Revenue Contributions", href: "/employees/revenue", icon: TrendingUp, anyOf: ["revenue.read"] },
      { label: "Salary", href: "/employees/salary", icon: Coins, anyOf: ["salary.read"] },
      { label: "Salary Formulas", href: "/employees/salary-formulas", icon: BadgePercent, anyOf: ["comp_formulas.read"] },
    ],
  },
  {
    label: "Projects",
    icon: Briefcase,
    items: [
      { label: "All Projects", href: "/projects", icon: FolderKanban, hireLabel: "My Projects", anyOf: ["projects.read"] },
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
      { label: "Team Calendar", href: "/calendar/team", icon: UsersRound, hideForHire: true },
      { label: "Company Calendar", href: "/calendar/company", icon: Building2, hideForHire: true },
    ],
  },
  {
    label: "Reports",
    icon: BarChart3,
    items: [
      // Finance sees the company; anyone with salary.read sees their own months (or their teams').
      { label: "Monthly Summary", href: "/reports/monthly", icon: CalendarClock, anyOf: ["reports.financial", "salary.read"] },
      { label: "Cash Flow & Runway", href: "/reports/cash-flow", icon: Banknote, anyOf: ["reports.financial"] },
      { label: "Customer Analysis", href: "/reports/customers", icon: Handshake, anyOf: ["reports.financial"] },
      { label: "Income & Expense Trends", href: "/reports/trends", icon: LineChart, anyOf: ["reports.financial"] },
      { label: "Employee Performance", href: "/reports/employee-performance", icon: Gauge, anyOf: ["salary.read"] },
      { label: "Financial Statements", href: "/accounting/statements", icon: Scale, anyOf: ["reports.financial"] },
      { label: "By Category", href: "/reports/categories", icon: Tags, anyOf: ["reports.financial"] },
      { label: "Customer & Supplier Payments", href: "/reports/parties", icon: ReceiptText, anyOf: ["reports.financial"] },
      { label: "Employee Salary Report", href: "/reports/employees", icon: FileSpreadsheet, anyOf: ["salary.read"] },
    ],
  },
  {
    label: "Settings",
    icon: Settings,
    items: [
      { label: "Company", href: "/settings/company", icon: Building2, hideForHire: true },
      { label: "Users", href: "/settings/users", icon: UserCog, anyOf: ["users.manage"] },
      { label: "Roles & Permissions", href: "/settings/roles", icon: ShieldCheck, anyOf: ["roles.manage"] },
      { label: "Custom Categories", href: "/settings/categories", icon: Tags, hideForHire: true },
      { label: "Currencies & Rates", href: "/settings/currencies", icon: Coins, hideForHire: true },
      { label: "Payment Accounts", href: "/settings/payment-accounts", icon: Landmark, anyOf: ["payment_accounts.manage", "payments.create"] },
      { label: "Accounting Periods", href: "/settings/periods", icon: CalendarRange, anyOf: ["periods.close", "reports.financial"] },
      { label: "Salary Cycle", href: "/settings/salary-cycle", icon: CalendarClock, anyOf: ["salary.read", "salary.configure_cycle"] },
      { label: "Data Import", href: "/settings/imports", icon: Upload, anyOf: ["imports.manage"] },
      { label: "Bidding Sheets", href: "/settings/bidding", icon: Sheet, anyOf: ["bidding.manage"] },
      { label: "Backups", href: "/settings/backups", icon: DatabaseBackup, anyOf: ["backups.manage"] },
      { label: "Audit Log", href: "/settings/audit-logs", icon: History, anyOf: ["audit.read"] },
      { label: "System Checks", href: "/settings/system", icon: HeartPulse, anyOf: ["audit.read"] },
    ],
  },
];

export function canSee(item: NavItem, permissions: Record<string, string>, isHire = false): boolean {
  if (isHire && item.hideForHire) return false;
  if (item.allScope && permissions[item.allScope] !== "all") return false;
  return !item.anyOf?.length || item.anyOf.some((p) => p in permissions);
}

const HIRE_SCREENS = ["/dashboard", "/projects", "/accounting/payment-entries", "/calendar/me"];
const NOT_FOR_HIRES = ["/projects/financials", "/accounting/payment-entries/new"];

/** The screens a hired manager can open. Anything else sends them to their dashboard; the API refuses it anyway. */
export function hireMayOpen(pathname: string): boolean {
  const within = (root: string) => pathname === root || pathname.startsWith(`${root}/`);
  return HIRE_SCREENS.some(within) && !NOT_FOR_HIRES.some(within);
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
