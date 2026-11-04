"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CalendarDays, ChevronDown, ChevronRight, Diamond, Flag, ListChecks, Plus } from "lucide-react";
import Link from "next/link";
import { Fragment, useState, type ReactNode } from "react";

import { BiddingDashboardSection, BiddingTiles } from "@/components/bidding/dashboard-section";
import { num, PeriodChart, SERIES } from "@/components/charts/charts";
import { PageHeader } from "@/components/erp/page-header";
import { shortLabel } from "@/components/reports/shared";
import { StatusBadge } from "@/components/payments/entry-view";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { formatAmount, formatShort, sign, subtract, sum } from "@/lib/money";
import { currencyPrecision, useCompany, useCurrencies } from "@/lib/queries";
import { useMe } from "@/lib/session";
import { addDays, fmtDay, fmtTime, iso } from "@/components/calendar/utils";
import { isOverdue } from "@/components/projects/shared";
import type { CalendarFeed, CashFlow, CompanyDashboard, EmployeeSalary, Holdings, MonthlySummary, Page, PaymentEntry, Task } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";


function Kpi({ label, value, base, tone, hint }: { label: string; value: string | undefined; base: string; tone?: "good" | "bad"; hint?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        {value === undefined ? <Skeleton className="mt-1 h-8 w-32" /> : (
          <p className={`tabular mt-1 text-2xl font-semibold ${tone === "bad" ? "text-destructive" : tone === "good" ? "text-success" : ""}`}>
            {formatAmount(value)} <span className="text-sm font-normal text-muted-foreground">{base}</span>
          </p>
        )}
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function TopTiles({ children }: { children: ReactNode }) {
  return <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{children}</div>;
}

function FinanceOverview({ tiles }: { tiles: ReactNode }) {
  const base = useCompany().data?.base_currency ?? "USD";
  const currencies = useCurrencies();
  const holdings = useQuery({ queryKey: ["holdings"], queryFn: () => api.get<Holdings>("/reports/holdings") });
  // "This month" is the current salary period (e.g. Oct 25 – Nov 24), not the calendar month.
  const dash = useQuery({ queryKey: ["dashboard-company"], queryFn: () => api.get<CompanyDashboard>("/dashboard/company") });
  const d = dash.data;
  const span = d ? `${d.period_label} · ${formatDate(d.period_start)} – ${formatDate(d.period_end)}` : undefined;
  const recent = useQuery({ queryKey: ["payment-entries", "recent"], queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { page_size: 6 }) });
  const h = holdings.data;
  const fx = h ? subtract(h.market_total, h.book_total) : "0";
  const monthly = useQuery({ queryKey: ["report-monthly", 12], queryFn: () => api.get<MonthlySummary>("/reports/monthly-summary", { periods: 12 }) });
  const cash = useQuery({ queryKey: ["report-cash-flow", 4], queryFn: () => api.get<CashFlow>("/reports/cash-flow", { periods: 4 }) });
  // Last full month, to read this month's (partial) figures against.
  const prev = monthly.data?.rows.filter((m) => !m.in_progress).at(-1);
  const run = cash.data?.runway;
  const runway = run && sign(run.cash_now) > 0
    ? run.months_net ? `Runway about ${run.months_net} months at the recent pace` : sign(run.net_burn) <= 0 && run.basis_periods ? "Cash has been growing" : undefined
    : undefined;
  return (
    <>
      <TopTiles>
        <Kpi
          label="Cash, bank & wallets"
          value={h?.market_total}
          base={base}
          hint={[h && sign(fx) ? `At today's rates · ${formatAmount(h.book_total)} as recorded` : "At today's rates", runway].filter(Boolean).join(" · ")}
        />
        <Kpi label="Income this month" value={d?.income} base={base} hint={[span, prev && `${prev.label}: ${formatAmount(prev.income)}`].filter(Boolean).join(" · ")} />
        <Kpi
          label="Expenses this month"
          value={d && sum([d.expenses, d.salary_paid])}
          base={base}
          hint={[d && `incl. ${formatAmount(d.salary_paid)} salary paid`, prev && `${prev.label}: ${formatAmount(sum([prev.expenses, prev.salary_paid]))}`].filter(Boolean).join(" · ")}
        />
        <Kpi
          label="Net profit this month"
          value={d?.profit}
          base={base}
          tone={d && sign(d.profit) < 0 ? "bad" : "good"}
          hint={[span, prev && `${prev.label}: ${formatAmount(prev.profit)}`].filter(Boolean).join(" · ")}
        />
        {tiles}
      </TopTiles>
      {monthly.data && monthly.data.rows.some((m) => sign(m.income) || sign(m.expenses) || sign(m.salary_paid)) && (
        <Card className="mb-6">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Last 12 months</CardTitle>
            <Button variant="ghost" size="sm" asChild><Link href="/reports/monthly">Monthly summary <ArrowRight /></Link></Button>
          </CardHeader>
          <CardContent>
            <PeriodChart
              label="Income, costs and profit over the last 12 months"
              height={220}
              unit={base}
              data={monthly.data.rows.map((m) => ({ label: shortLabel(m.label), income: num(m.income), costs: num(m.expenses) + num(m.salary_paid), profit: num(m.profit) }))}
              bars={[{ key: "income", label: "Income", color: SERIES[0] }, { key: "costs", label: "Expenses + salary", color: SERIES[1] }]}
              line={{ key: "profit", label: "Profit", color: SERIES[3] }}
            />
          </CardContent>
        </Card>
      )}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Salary owed" value={d?.salary_owed} base={base} hint="Earned by employees, not paid yet" />
        <Kpi label="Salary this month" value={d?.salary_projected} base={base} hint="Projected from revenue so far" />
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-muted-foreground">Tasks</p>
            {!d ? <Skeleton className="mt-1 h-8 w-32" /> : (
              <p className="mt-1 text-2xl font-semibold">
                <span className={cn("tabular", d.tasks_overdue > 0 && "text-destructive")}>{d.tasks_overdue}</span>{" "}
                <span className="text-sm font-normal text-muted-foreground">overdue · {d.tasks_due_soon} due this week · {d.tasks_open} open</span>
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-muted-foreground">Active projects</p>
            {!d ? <Skeleton className="mt-1 h-8 w-32" /> : (
              <p className="mt-1 text-2xl font-semibold">
                <span className="tabular">{d.projects_active}</span>{" "}
                <span className={cn("text-sm font-normal", d.at_risk.length ? "text-warning" : "text-muted-foreground")}>{d.at_risk.length} need attention</span>
              </p>
            )}
          </CardContent>
        </Card>
      </div>
      {d && (d.at_risk.length > 0 || d.upcoming.length > 0) && (
        <div className="mb-6 grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-warning" /> Projects needing attention</CardTitle></CardHeader>
            <CardContent>
              {d.at_risk.length === 0 ? <p className="text-sm text-muted-foreground">None. All active projects are on track.</p> : (
                <ul className="flex flex-col gap-2 text-sm">
                  {d.at_risk.map((r) => (
                    <li key={r.project_id}>
                      <Link href={`/projects/${r.project_id}?tab=financials`} className="font-medium hover:underline">{r.name}</Link>
                      <span className="text-muted-foreground"> · {r.reasons.join(", ")}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Coming up (2 weeks)</CardTitle></CardHeader>
            <CardContent>
              {d.upcoming.length === 0 ? <p className="text-sm text-muted-foreground">No milestones or deadlines.</p> : (
                <ul className="flex flex-col gap-1.5 text-sm">
                  {d.upcoming.map((u, i) => (
                    <li key={i} className="flex items-center gap-2">
                      {u.kind === "milestone" ? <Diamond className="size-3.5 text-violet-500" /> : <Flag className="size-3.5 text-destructive" />}
                      <span className="w-24 shrink-0 text-muted-foreground">{formatDate(u.date)}</span>
                      <Link href={u.link} className="truncate hover:underline">{u.kind === "deadline" ? `Deadline: ${u.title}` : u.title}</Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}
      {h && <AssetsByCurrency holdings={h} />}
      <Card className="mb-6">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Recent payments</CardTitle>
          <Button variant="ghost" size="sm" asChild><Link href="/accounting/payment-entries">All payments <ArrowRight /></Link></Button>
        </CardHeader>
        <CardContent>
          {!recent.data ? <Skeleton className="h-24 w-full" /> : recent.data.items.length === 0 ? (
            <div className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
              No payments yet.
              <Button size="sm" asChild><Link href="/accounting/payment-entries/new"><Plus /> Record the first payment</Link></Button>
            </div>
          ) : (
            <ul className="divide-y">
              {recent.data.items.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <Link href={`/accounting/payment-entries/${e.id}`} className="min-w-0 hover:underline">
                    <span className="font-mono text-xs text-muted-foreground">{e.number}</span>{" "}
                    {e.party_name ?? (e.direction === "internal_transfer" ? "Internal transfer" : "—")}
                    <span className="text-muted-foreground"> · {formatDate(e.posting_date)}</span>
                  </Link>
                  <span className="flex shrink-0 items-center gap-3">
                    <span className="tabular">{e.direction === "pay" ? "−" : ""}{formatShort(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}</span>
                    <StatusBadge status={e.status} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}

/** Money held per currency: units, recorded value, and value at the saved rate (display only, nothing posted). */
function AssetsByCurrency({ holdings }: { holdings: Holdings }) {
  const currencies = useCurrencies();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const base = holdings.base_currency;
  const shown = holdings.currencies.filter((c) => sign(c.units) !== 0 || sign(c.book_value) !== 0);
  const totalDiff = subtract(holdings.market_total, holdings.book_total);
  const toggle = (code: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(code)) n.delete(code);
      else n.add(code);
      return n;
    });
  return (
    <Card className="mb-6">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>Assets by currency</CardTitle>
          <CardDescription>
            Cash, bank accounts, wallets and cards in their own currency. &quot;At today&apos;s rate&quot; uses the latest saved rate
            (Settings → Currencies &amp; Rates); &quot;as recorded&quot; is what the books hold.
          </CardDescription>
        </div>
        <Button variant="ghost" size="sm" asChild><Link href="/settings/currencies">Rates <ArrowRight /></Link></Button>
      </CardHeader>
      <CardContent>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">No money held yet.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="w-8" />
                <TH>Currency</TH>
                <TH className="text-right">Amount held</TH>
                <TH className="text-right">Rate</TH>
                <TH className="text-right">At today&apos;s rate ({base})</TH>
                <TH className="text-right">As recorded ({base})</TH>
                <TH className="text-right">Difference</TH>
              </TR>
            </THead>
            <TBody>
              {shown.map((c) => {
                const expanded = open.has(c.currency);
                const diff = c.market_value != null ? subtract(c.market_value, c.book_value) : null;
                const precision = currencyPrecision(currencies.data, c.currency);
                return (
                  <Fragment key={c.currency}>
                    <TR>
                      <TD>
                        <Button variant="ghost" size="icon" aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} ${c.currency} accounts`} onClick={() => toggle(c.currency)}>
                          {expanded ? <ChevronDown /> : <ChevronRight />}
                        </Button>
                      </TD>
                      <TD className="font-medium">{c.currency}</TD>
                      <TD className="tabular text-right">{formatShort(c.units, precision)} {c.currency}</TD>
                      <TD className="tabular text-right">
                        {c.currency === base ? "—" : c.rate ? (
                          <span title={c.rate_date ? `Saved for ${formatDate(c.rate_date)}` : undefined}>{formatAmount(c.rate, 4)}</span>
                        ) : <span className="text-warning">no rate</span>}
                      </TD>
                      <TD className="tabular text-right font-medium">{c.market_value != null ? formatAmount(c.market_value) : "—"}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(c.book_value)}</TD>
                      <TD className={cn("tabular text-right", diff && sign(diff) < 0 && "text-destructive", diff && sign(diff) > 0 && "text-success")}>
                        {diff && sign(diff) ? `${sign(diff) > 0 ? "+" : ""}${formatAmount(diff)}` : "—"}
                      </TD>
                    </TR>
                    {expanded && c.accounts.map((a) => (
                      <TR key={a.account_id} className="bg-muted/30 text-sm">
                        <TD />
                        <TD className="pl-6 text-muted-foreground">{a.code} {a.name}</TD>
                        <TD className="tabular text-right">{formatShort(a.units, precision)}</TD>
                        <TD />
                        <TD className="tabular text-right">{a.market_value != null ? formatAmount(a.market_value) : "—"}</TD>
                        <TD className="tabular text-right text-muted-foreground">{formatAmount(a.book_value)}</TD>
                        <TD />
                      </TR>
                    ))}
                  </Fragment>
                );
              })}
              <TR className="font-medium">
                <TD />
                <TD>Total</TD>
                <TD />
                <TD />
                <TD className="tabular text-right">{formatAmount(holdings.market_total)}</TD>
                <TD className="tabular text-right text-muted-foreground">{formatAmount(holdings.book_total)}</TD>
                <TD className="tabular text-right">{sign(totalDiff) ? formatAmount(totalDiff) : "—"}</TD>
              </TR>
            </TBody>
          </Table>
        )}
        {holdings.missing_rates.length > 0 && (
          <p className="mt-3 text-xs text-warning">No saved rate for {holdings.missing_rates.join(", ")}: counted at the recorded value in the total.</p>
        )}
      </CardContent>
    </Card>
  );
}

/** Employee view of the money side: own revenue, expenses and salary (from /me/salary) and own payments.
 * The API scopes both to the signed-in employee, so nothing about colleagues or company totals shows. */
function EmployeeOverview({ showRevenue, tiles }: { showRevenue: boolean; tiles: ReactNode }) {
  const base = useCompany().data?.base_currency ?? "USD";
  const currencies = useCurrencies();
  const salary = useQuery({ queryKey: ["me-salary"], queryFn: () => api.get<EmployeeSalary>("/me/salary"), retry: false });
  const recent = useQuery({
    queryKey: ["payment-entries", "recent", "mine"],
    queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { page_size: 6 }),
    enabled: salary.isSuccess,
  });
  if (salary.isError) {
    return (
      <>
        {salary.error instanceof ApiError && salary.error.status === 404 && (
          <Card className="mb-6">
            <CardContent className="py-4 text-sm text-muted-foreground">
              Your sign-in isn&apos;t linked to an employee record yet, so there are no revenue or salary figures to show. Ask an administrator to link it.
            </CardContent>
          </Card>
        )}
        {tiles && <TopTiles>{tiles}</TopTiles>}
      </>
    );
  }
  const s = salary.data;
  const cur = s?.current;
  const span = cur ? `${cur.period_label} · ${formatDate(cur.period_start)} – ${formatDate(cur.period_end)}` : undefined;
  // statements are newest first; the chart reads oldest to newest.
  const months = (s?.statements ?? []).slice(0, 12).reverse();
  const prev = s?.statements.find((x) => x.period_id !== cur?.period_id);
  return (
    <>
      <TopTiles>
        {showRevenue && (
          <>
            <Kpi label="My revenue this month" value={s ? (cur?.gross_revenue ?? "0") : undefined} base={base}
              hint={[span ?? "Credited from customer payments", prev && `${prev.period_label}: ${formatAmount(prev.gross_revenue)}`].filter(Boolean).join(" · ")} />
            <Kpi label="My expenses this month" value={s ? (cur?.expenses ?? "0") : undefined} base={base}
              hint={[`Net ${formatAmount(cur?.revenue ?? "0")}`, prev && `${prev.period_label}: ${formatAmount(prev.expenses)}`].filter(Boolean).join(" · ")} />
          </>
        )}
        <Kpi label="My salary this month" value={s ? (cur?.calculated ?? "0") : undefined} base={base}
          hint={[cur?.period_status === "open" ? "Projected from revenue so far" : cur?.period_label, cur && sign(cur.paid) ? `${formatAmount(cur.paid)} paid` : undefined].filter(Boolean).join(" · ")} />
        <Kpi label="Salary owed to me" value={s?.balance} base={base} tone={s && sign(s.balance) > 0 ? "good" : undefined}
          hint={s ? `${formatAmount(s.paid_total)} paid of ${formatAmount(s.calculated_total)} earned in total` : undefined} />
        {tiles}
      </TopTiles>
      {months.some((m) => sign(m.gross_revenue) || sign(m.expenses) || sign(m.calculated)) && (
        <Card className="mb-6">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Last 12 months</CardTitle>
            <Button variant="ghost" size="sm" asChild><Link href="/me">My salary <ArrowRight /></Link></Button>
          </CardHeader>
          <CardContent>
            <PeriodChart
              label={showRevenue ? "My revenue, expenses and salary over the last 12 months" : "My salary over the last 12 months"}
              height={220}
              unit={base}
              data={months.map((m) => ({ label: shortLabel(m.period_label), revenue: num(m.gross_revenue), expenses: num(m.expenses), salary: num(m.calculated), paid: num(m.paid) }))}
              bars={showRevenue
                ? [{ key: "revenue", label: "Revenue", color: SERIES[0] }, { key: "expenses", label: "Expenses", color: SERIES[1] }]
                : [{ key: "paid", label: "Paid", color: SERIES[0] }]}
              line={{ key: "salary", label: "Salary", color: SERIES[3] }}
            />
          </CardContent>
        </Card>
      )}
      <Card className="mb-6">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>My recent payments</CardTitle>
          <Button variant="ghost" size="sm" asChild><Link href="/accounting/payment-entries">All my payments <ArrowRight /></Link></Button>
        </CardHeader>
        <CardContent>
          {!recent.data ? <Skeleton className="h-24 w-full" /> : recent.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No payments involving you yet.</p>
          ) : (
            <ul className="divide-y">
              {recent.data.items.map((e) => {
                const out = e.direction === "pay";
                return (
                  <li key={e.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <Link href={`/accounting/payment-entries/${e.id}`} className="min-w-0 hover:underline">
                      <span className="font-mono text-xs text-muted-foreground">{e.number}</span>{" "}
                      {e.party_name ?? e.employee_name ?? "—"}
                      <span className="text-muted-foreground"> · {formatDate(e.posting_date)}</span>
                    </Link>
                    <span className="flex shrink-0 items-center gap-3">
                      <span className={cn("tabular text-right", !out && "text-success")}>
                        {out ? "−" : ""}
                        {e.my_share != null
                          ? <>{formatShort(e.my_share)} {base} <span className="text-xs text-muted-foreground">your share</span></>
                          : <>{formatShort(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}</>}
                      </span>
                      <StatusBadge status={e.status} />
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}

/** My next seven days: tasks due (and overdue) plus calendar events. */
function MyWeek() {
  const today = iso(new Date());
  const end = addDays(today, 7);
  const tasks = useQuery({
    queryKey: ["tasks", "my-week"],
    queryFn: async () => {
      const qs = new URLSearchParams([["assignee", "me"], ["page_size", "100"], ...["backlog", "todo", "in_progress", "review"].map((x) => ["status", x])]);
      return (await api.get<Page<Task>>(`/tasks?${qs}`)).items;
    },
  });
  const feed = useQuery({ queryKey: ["calendar", "my-week", today], queryFn: () => api.get<CalendarFeed>("/calendar/feed", { from: today, to: end, view: "me" }) });
  const due = (tasks.data ?? []).filter((t) => t.due_date && t.due_date <= end).sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1));
  const events = (feed.data?.items ?? []).filter((i) => i.kind === "event" || i.kind === "leave").slice(0, 8);
  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>This week</CardTitle>
        <Button variant="ghost" size="sm" asChild><Link href="/calendar/me">Calendar <ArrowRight /></Link></Button>
      </CardHeader>
      <CardContent className="grid gap-6 sm:grid-cols-2">
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"><ListChecks className="size-3.5" /> My tasks due</p>
          {!tasks.data ? <Skeleton className="h-16 w-full" /> : due.length === 0 ? <p className="text-sm text-muted-foreground">Nothing due.</p> : (
            <ul className="flex flex-col gap-1 text-sm">
              {due.slice(0, 8).map((t) => (
                <li key={t.id} className="flex gap-2">
                  <span className={cn("w-20 shrink-0", isOverdue(t.due_date, t.status) ? "font-medium text-destructive" : "text-muted-foreground")}>{fmtDay(t.due_date!, { weekday: "short", day: "numeric" })}</span>
                  <Link href={`/projects/${t.project_id}?tab=tasks`} className="truncate hover:underline">{t.title}</Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"><CalendarDays className="size-3.5" /> Events</p>
          {!feed.data ? <Skeleton className="h-16 w-full" /> : events.length === 0 ? <p className="text-sm text-muted-foreground">No events.</p> : (
            <ul className="flex flex-col gap-1 text-sm">
              {events.map((i) => (
                <li key={i.key} className="flex gap-2">
                  <span className="w-20 shrink-0 text-muted-foreground">{fmtDay(i.start.slice(0, 10), { weekday: "short", day: "numeric" })}{i.all_day ? "" : ` ${fmtTime(i.start)}`}</span>
                  <span className="truncate">{i.title}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const me = useMe();
  const firstName = me.full_name.split(/\s+/)[0];
  const finance = "reports.financial" in me.permissions;
  const mySalary = "salary.read" in me.permissions;
  const bidding = "bidding.read" in me.permissions;
  const biddingTiles = bidding ? <BiddingTiles /> : null;
  const quickLinks = [
    { href: "/accounting/payment-entries/new", label: "Record a payment", show: "payments.create" in me.permissions },
    { href: "/parties/customers", label: "Customers", show: "parties.read" in me.permissions },
    { href: "/me", label: "My salary", show: "salary.read" in me.permissions && !finance },
    { href: "/employees/salary", label: "Salary board", show: "salary.read" in me.permissions && finance },
    { href: "/employees", label: "Employees", show: "employees.read" in me.permissions },
    { href: "/projects/tasks", label: "My tasks", show: "projects.read" in me.permissions },
    { href: "/calendar/me", label: "My calendar", show: true },
    { href: "/projects", label: "Projects", show: "projects.read" in me.permissions },
    { href: "/settings/imports", label: "Import existing data", show: "imports.manage" in me.permissions },
    { href: "/settings/company", label: "Company settings", show: true },
  ].filter((l) => l.show);

  return (
    <>
      <PageHeader
        title={`Welcome, ${firstName}`}
        description={finance ? "This month at a glance, from the posted ledger." : mySalary ? "Your month at a glance: your revenue, expenses, salary and payments." : undefined}
      />
      {finance ? (
        <FinanceOverview tiles={biddingTiles} />
      ) : mySalary ? (
        <EmployeeOverview showRevenue={"revenue.read" in me.permissions} tiles={biddingTiles} />
      ) : (
        biddingTiles && <TopTiles>{biddingTiles}</TopTiles>
      )}
      {bidding && <BiddingDashboardSection />}
      <div className="grid gap-6 lg:grid-cols-3">
        <MyWeek />
        <Card>
          <CardHeader><CardTitle>Shortcuts</CardTitle></CardHeader>
          <CardContent>
            <ul className="flex flex-col">
              {quickLinks.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="flex items-center justify-between rounded-md px-2 py-2 text-sm hover:bg-muted">
                    {l.label} <ArrowRight className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
