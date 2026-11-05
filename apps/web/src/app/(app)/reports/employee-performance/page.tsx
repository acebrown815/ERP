"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Receipt } from "lucide-react";
import Link from "next/link";

import { DateRange, useReportRange } from "@/components/accounting/report-controls";
import { num, PeriodChart, SERIES, Sparkline, StatTile } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { paymentsHref, shortLabel } from "@/components/reports/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import { useCompany } from "@/lib/queries";
import type { Performance } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Salary above this share of the revenue someone brings in is flagged. */
const HIGH_SALARY_PCT = 50;

export default function EmployeePerformancePage() {
  const base = useCompany().data?.base_currency ?? "USD";
  const { range, setRange, ready } = useReportRange("last_6");
  const q = useQuery({
    queryKey: ["report-employee-performance", range],
    queryFn: () => api.get<Performance>("/reports/employee-performance", range),
    placeholderData: keepPreviousData,
    enabled: ready,
  });
  const r = q.data;
  const t = r?.totals;
  const first = r?.periods[0];
  const last = r?.periods.at(-1);
  const span = first && last ? (first.id === last.id ? first.label : `${first.label} – ${last.label}`) : "";

  return (
    <>
      <PageHeader
        title="Employee performance"
        description={`What each person brings in, what they cost, and what is left for the company (${base}). Revenue is net of expenses tagged to them; salary is what they earned, paid or not; shared expenses are their part of split expenses (reports only).`}
        actions={
          <>
            <DateRange {...range} onChange={setRange} wholePeriods />
            <ExportMenu path="/reports/employee-performance" params={range} />
          </>
        }
      />
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 || !t ? (
        <EmptyState title="No revenue or salary in these periods" />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Net revenue" value={formatAmount(t.net_revenue)} unit={base} hint={`${span} · after ${formatAmount(t.expenses)} tagged expenses`} />
            <StatTile label="Salary earned" value={formatAmount(t.salary)} unit={base} hint={span} />
            <StatTile
              label="Left for the company"
              value={formatAmount(t.contribution)}
              unit={base}
              tone={sign(t.contribution) < 0 ? "bad" : undefined}
              hint="Net revenue − salary"
              spark={<Sparkline values={t.contribution_by_period.map(num)} color={SERIES[2]} label="Left for the company per period" />}
            />
            <StatTile
              label="Salary as % of revenue"
              value={t.salary_pct ? `${t.salary_pct}%` : "—"}
              hint={t.revenue_per_hour ? `${formatAmount(t.revenue_per_hour)} ${base} revenue per hour logged` : "No hours logged on tasks"}
            />
          </div>

          <Card className="mb-6">
            <CardHeader><CardTitle>Revenue, salary and what is left, per person</CardTitle><CardDescription>{span}</CardDescription></CardHeader>
            <CardContent>
              <PeriodChart
                label="Net revenue, salary and contribution per employee"
                xKey="name"
                data={r.rows.map((x) => ({ name: x.employee_name, revenue: num(x.net_revenue), salary: num(x.salary), left: num(x.contribution) }))}
                unit={base}
                bars={[
                  { key: "revenue", label: "Net revenue", color: SERIES[0] },
                  { key: "salary", label: "Salary earned", color: SERIES[1] },
                  { key: "left", label: "Left for the company", color: SERIES[2] },
                ]}
              />
            </CardContent>
          </Card>

          <Card className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Employee</TH>
                  <TH className="text-right">Revenue</TH>
                  <TH className="text-right">Expenses</TH>
                  <TH className="text-right">Net revenue</TH>
                  <TH className="text-right">Salary</TH>
                  <TH className="text-right" title="Their share of expenses split between employees (not in salary)">Shared expenses</TH>
                  <TH className="text-right">Left for company</TH>
                  <TH className="text-right" title="Salary earned as a share of net revenue">Salary %</TH>
                  <TH className="text-right">Hours</TH>
                  <TH className="text-right">Revenue / hour</TH>
                  <TH title={r.periods.map((p) => shortLabel(p.label)).join(", ")}>Trend</TH>
                  <TH className="w-8" />
                </TR>
              </THead>
              <TBody>
                {r.rows.map((x) => {
                  const high = x.salary_pct !== null && x.salary_pct !== undefined && Number(x.salary_pct) > HIGH_SALARY_PCT;
                  return (
                    <TR key={x.employee_id}>
                      <TD><Link href={`/employees/${x.employee_id}`} className="font-medium hover:underline">{x.employee_name}</Link></TD>
                      <TD className="tabular text-right">{formatAmount(x.gross_revenue)}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(x.expenses)}</TD>
                      <TD className={cn("tabular text-right", sign(x.net_revenue) < 0 && "text-destructive")}>{formatAmount(x.net_revenue)}</TD>
                      <TD className="tabular text-right">{formatAmount(x.salary)}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(x.shared_expenses)}</TD>
                      <TD className={cn("tabular text-right font-medium", sign(x.contribution) < 0 && "text-destructive")}>{formatAmount(x.contribution)}</TD>
                      <TD className={cn("tabular text-right", high && "font-medium text-destructive")} title={high ? `Above ${HIGH_SALARY_PCT}% of what they bring in` : undefined}>
                        {x.salary_pct ? `${x.salary_pct}%` : "—"}
                      </TD>
                      <TD className="tabular text-right text-muted-foreground">{num(x.hours) ? formatAmount(x.hours, 1) : "—"}</TD>
                      <TD className="tabular text-right">{x.revenue_per_hour ? formatAmount(x.revenue_per_hour) : "—"}</TD>
                      <TD><Sparkline values={x.contribution_by_period.map(num)} color={SERIES[2]} label={`${x.employee_name}: left for the company per period`} /></TD>
                      <TD>
                        {first && last && (
                          <Link href={paymentsHref({ employee_id: x.employee_id, from: first.start_date, to: last.end_date })} title="Payments for this person" aria-label={`Payments for ${x.employee_name}`} className="text-muted-foreground hover:text-foreground">
                            <Receipt className="size-4" />
                          </Link>
                        )}
                      </TD>
                    </TR>
                  );
                })}
                <TR className="font-medium">
                  <TD>Total</TD>
                  <TD className="tabular text-right">{formatAmount(t.gross_revenue)}</TD>
                  <TD className="tabular text-right">{formatAmount(t.expenses)}</TD>
                  <TD className="tabular text-right">{formatAmount(t.net_revenue)}</TD>
                  <TD className="tabular text-right">{formatAmount(t.salary)}</TD>
                  <TD className="tabular text-right">{formatAmount(t.shared_expenses)}</TD>
                  <TD className={cn("tabular text-right", sign(t.contribution) < 0 && "text-destructive")}>{formatAmount(t.contribution)}</TD>
                  <TD className="tabular text-right">{t.salary_pct ? `${t.salary_pct}%` : "—"}</TD>
                  <TD className="tabular text-right">{num(t.hours) ? formatAmount(t.hours, 1) : "—"}</TD>
                  <TD className="tabular text-right">{t.revenue_per_hour ? formatAmount(t.revenue_per_hour) : "—"}</TD>
                  <TD colSpan={2} />
                </TR>
              </TBody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}
