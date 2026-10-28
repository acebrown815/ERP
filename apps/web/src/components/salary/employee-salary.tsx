"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import { useCompany, useSalaryPeriods } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { EmployeeRevenue, EmployeeSalary, FormulaPreview } from "@/lib/types";
import { formatDate } from "@/lib/utils";

import { RateChart } from "./rate-chart";
import { Breakdown, defaultPeriod, formatRate, PeriodSelect, periodRange, SalaryStatus, summarize } from "./shared";

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "good" | "warn" }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className={`tabular mt-1 text-2xl font-semibold ${tone === "good" ? "text-success" : ""}`}>{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Revenue({ employeeId }: { employeeId: string }) {
  const periods = useSalaryPeriods();
  const [periodId, setPeriodId] = useState<string>();
  const selected = periodId ?? defaultPeriod(periods.data)?.id;
  const q = useQuery({
    queryKey: ["employee-revenue", employeeId, selected],
    queryFn: () => api.get<EmployeeRevenue>(`/employees/${employeeId}/revenue`, { salary_period_id: selected }),
    enabled: !!selected,
  });
  const r = q.data;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle>Revenue and expenses</CardTitle>
          <CardDescription>Customer payments split to this employee, minus expenses tagged to them. The net is what the salary formula is applied to.</CardDescription>
        </div>
        {periods.data && <PeriodSelect id="rev_period" periods={periods.data} value={selected} onChange={setPeriodId} />}
      </CardHeader>
      <CardContent>
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton rows={3} /> : r.allocations.length === 0 && r.expenses.length === 0 ? (
          <p className="text-sm text-muted-foreground">No revenue or expenses in {r.period.label} ({periodRange(r.period)}).</p>
        ) : (
          <>
          <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
            <div>
              <p className={`tabular text-2xl font-semibold ${sign(r.net) < 0 ? "text-destructive" : ""}`}>{formatAmount(r.net)}</p>
              <p className="text-xs text-muted-foreground">net · {r.period.label} · {periodRange(r.period)}</p>
              <p className="mb-3 text-xs text-muted-foreground">{formatAmount(r.total)} revenue − {formatAmount(r.expenses_total)} expenses</p>
              <ul className="flex flex-col gap-1 text-sm">
                {r.by_project.map((p) => (
                  <li key={p.project_id ?? "none"} className="flex justify-between gap-2">
                    <span className="truncate">{p.project_name ?? "No project"} <span className="text-muted-foreground">· {p.payments}</span></span>
                    <span className="tabular">{formatAmount(p.revenue)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <Table>
              <THead><TR><TH>Date</TH><TH>Payment</TH><TH>Project</TH><TH className="text-right">Share</TH><TH className="text-right">Amount</TH></TR></THead>
              <TBody>
                {r.allocations.map((a) => (
                  <TR key={`${a.payment_entry_id}`}>
                    <TD>{formatDate(a.date)}</TD>
                    <TD className="font-mono text-xs">{a.payment_number}</TD>
                    <TD>{a.project_name ?? "—"}</TD>
                    <TD className="tabular text-right">{a.percent ? `${formatAmount(a.percent)}%` : "fixed"}</TD>
                    <TD className="tabular text-right">{formatAmount(a.amount)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
          {r.expenses.length > 0 && (
            <div className="mt-6">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Expenses tagged to this employee</p>
              <Table>
                <THead><TR><TH>Date</TH><TH>Payment</TH><TH>Project</TH><TH className="text-right">Amount</TH></TR></THead>
                <TBody>
                  {r.expenses.map((x) => (
                    <TR key={x.payment_entry_id}>
                      <TD>{formatDate(x.date)}</TD>
                      <TD className="font-mono text-xs">{x.payment_number}</TD>
                      <TD>{x.project_name ?? "—"}</TD>
                      <TD className="tabular text-right">−{formatAmount(x.amount)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function FormulaCard({ salary }: { salary: EmployeeSalary }) {
  const f = salary.formula;
  const chart = useQuery({
    queryKey: ["formula-preview", f?.definition],
    queryFn: () => api.post<FormulaPreview>("/comp-formulas/preview", { definition: f!.definition }),
    enabled: !!f,
  });
  if (!f) {
    return (
      <Card>
        <CardHeader><CardTitle>Salary formula</CardTitle></CardHeader>
        <CardContent><p className="text-sm text-muted-foreground">No formula is assigned for the current period, so revenue doesn&apos;t turn into salary yet.</p></CardContent>
      </Card>
    );
  }
  const current = salary.current;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{f.formula_name}</CardTitle>
        <CardDescription>Version {f.version_no} · {summarize(f.definition)}</CardDescription>
      </CardHeader>
      <CardContent>
        {chart.data && <RateChart points={chart.data.chart} />}
        {current && (
          <p className="mt-3 text-sm">
            This period so far: net revenue <strong className="tabular">{formatAmount(current.revenue)}</strong> → rate{" "}
            <strong className="tabular">{formatRate(current.rate)}</strong> → salary <strong className="tabular">{formatAmount(current.calculated)}</strong>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** Balance, current period, formula, statements, payments and revenue for one employee (read-only). */
export function EmployeeSalaryView({ employeeId, path, showRevenue = true }: { employeeId: string; path: string; showRevenue?: boolean }) {
  const base = useCompany().data?.base_currency ?? "USD";
  const q = useQuery({ queryKey: ["employee-salary", employeeId, path], queryFn: () => api.get<EmployeeSalary>(path) });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  if (!s) return <TableSkeleton />;
  const cur = s.current;
  const bal = sign(s.balance);
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={`Net revenue this period${cur ? ` (${cur.period_label})` : ""}`}
          value={`${formatAmount(cur?.revenue ?? "0")} ${base}`}
          hint={cur ? `${formatAmount(cur.gross_revenue)} revenue − ${formatAmount(cur.expenses)} expenses · ${periodRange({ start_date: cur.period_start, end_date: cur.period_end })}` : undefined}
        />
        <Stat label="Projected salary this period" value={`${formatAmount(cur?.calculated ?? "0")} ${base}`} hint={cur?.formula_name ? `at ${formatRate(cur.rate)}` : "No formula"} />
        <Stat label="Salary balance" value={`${formatAmount(s.balance)} ${base}`} hint={bal > 0 ? "Owed, not yet paid" : bal < 0 ? "Paid ahead" : "All settled"} />
        <Stat label="Paid to date" value={`${formatAmount(s.paid_total)} ${base}`} hint={`of ${formatAmount(s.calculated_total)} calculated`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <FormulaCard salary={s} />
        {cur && (
          <Card>
            <CardHeader>
              <CardTitle>{cur.period_label} breakdown</CardTitle>
              <CardDescription>{cur.period_status === "open" ? "Projected: updates as payments come in until the period is closed." : "Final."}</CardDescription>
            </CardHeader>
            <CardContent><Breakdown components={cur.components} total={cur.calculated} /></CardContent>
          </Card>
        )}
      </div>

      <Card>
        <CardHeader><CardTitle>Salary by period</CardTitle></CardHeader>
        <CardContent>
          {s.statements.length === 0 ? <p className="text-sm text-muted-foreground">No salary yet.</p> : (
            <Table>
              <THead>
                <TR><TH>Period</TH><TH className="text-right">Revenue</TH><TH className="text-right">Expenses</TH><TH className="text-right">Net</TH><TH className="text-right">Rate</TH><TH className="text-right">Calculated</TH><TH className="text-right">Paid</TH><TH>Status</TH></TR>
              </THead>
              <TBody>
                {s.statements.map((x) => (
                  <TR key={x.period_id}>
                    <TD>
                      <span className="font-medium">{x.period_label}</span>{" "}
                      <span className="text-xs text-muted-foreground">{periodRange({ start_date: x.period_start, end_date: x.period_end })}{x.period_status === "closed" ? " · closed" : ""}</span>
                    </TD>
                    <TD className="tabular text-right">{formatAmount(x.gross_revenue)}</TD>
                    <TD className="tabular text-right text-muted-foreground">{sign(x.expenses) ? `−${formatAmount(x.expenses)}` : "—"}</TD>
                    <TD className={`tabular text-right ${sign(x.revenue) < 0 ? "text-destructive" : ""}`}>{formatAmount(x.revenue)}</TD>
                    <TD className="tabular text-right">{x.formula_name ? formatRate(x.rate) : "—"}</TD>
                    <TD className="tabular text-right">{formatAmount(x.calculated)}</TD>
                    <TD className="tabular text-right">{formatAmount(x.paid)}</TD>
                    <TD><SalaryStatus status={x.status} /></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Salary payments</CardTitle></CardHeader>
        <CardContent>
          {s.payments.length === 0 ? <p className="text-sm text-muted-foreground">None yet.</p> : (
            <Table>
              <THead><TR><TH>Date</TH><TH>Payment</TH><TH>For</TH><TH className="text-right">Amount</TH></TR></THead>
              <TBody>
                {s.payments.map((p) => (
                  <TR key={p.payment_entry_id}>
                    <TD>{formatDate(p.paid_on)}</TD>
                    <TD className="font-mono text-xs">
                      <PaymentLink id={p.payment_entry_id} number={p.number} />
                    </TD>
                    <TD>{p.period_label ?? <span className="text-muted-foreground">Oldest unpaid first</span>}</TD>
                    <TD className="tabular text-right">{formatAmount(p.amount)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {showRevenue && <Revenue employeeId={employeeId} />}
    </div>
  );
}

function PaymentLink({ id, number }: { id: string; number: string | null }) {
  const can = useCan();
  // Employees see their payments but can't open payment entries.
  if (!can("payments.create") && !can("reports.financial")) return <>{number}</>;
  return <Link href={`/accounting/payment-entries/${id}`} className="hover:underline">{number}</Link>;
}
