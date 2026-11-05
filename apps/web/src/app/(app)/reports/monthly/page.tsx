"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Delta, num, PeriodChart, SERIES, Sparkline, StatTile } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { type OwnerSelection, OwnerSelect } from "@/components/reports/owner-select";
import { DrillAmount, MonthsSelect, shortLabel } from "@/components/reports/shared";
import { periodRange } from "@/components/salary/shared";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign, sum } from "@/lib/money";
import { useCan } from "@/lib/session";
import type { Employee, MonthlySummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Month = MonthlySummary["rows"][number];

// Company: what left the business. Employee: their expenses plus the salary they earned (paid or not).
const costs = (r: Month, employee: boolean) => sum([r.expenses, employee ? r.salary_calculated : r.salary_paid]);

function Margin({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  return <span className={cn("tabular", sign(value) < 0 && "text-destructive")}>{value}%</span>;
}

export default function MonthlySummaryPage() {
  const can = useCan();
  const [periods, setPeriods] = useState(12);
  // Without reports.financial (an employee): only their own months, no company view and no picker.
  const financial = can("reports.financial");
  const me = useQuery({ queryKey: ["employee", "me"], queryFn: () => api.get<Employee>("/employees/me"), enabled: !financial, retry: false });
  const [chosen, setSelection] = useState<OwnerSelection>({ employeeIds: [], unassigned: false });
  const selection: OwnerSelection = financial ? chosen : { employeeIds: me.data ? [me.data.id] : [], unassigned: false };
  const params = {
    ...(selection.employeeIds.length ? { employee_ids: selection.employeeIds.join(",") } : {}),
    ...(selection.unassigned ? { unassigned: "true" } : {}),
  };
  // Load every month once, so any range can be compared with the same span just before it.
  const q = useQuery({
    queryKey: ["report-monthly", "all", selection],
    queryFn: () => api.get<MonthlySummary>("/reports/monthly-summary", { periods: 0, ...params }),
    placeholderData: keepPreviousData,
    enabled: financial || !!me.data,
  });
  const r = q.data;
  // A selection of employees and/or "Not assigned" rather than the whole company.
  const emp = !!r && (r.employee_ids.length > 0 || r.unassigned);
  const picked = r ? [...r.employee_names, ...(r.unassigned ? ["Not assigned"] : [])] : [];
  // Payments can be filtered to one employee only.
  const drillEmployee = r && r.employee_ids.length === 1 && !r.unassigned ? r.employee_ids[0] : null;
  const canDrill = financial || ["payments.create", "salary.read", "revenue.read"].some(can); // who can open Payment Entries
  const cost = (m: Month) => costs(m, emp);
  const L = emp
    ? { income: "Revenue", profit: "Contribution", salary: "Salary earned", costsHint: "Expenses + salary earned" }
    : { income: "Income", profit: "Profit", salary: "Salary paid", costsHint: "Expenses + salary paid" };
  const all = r?.rows ?? [];
  const rows = periods ? all.slice(-periods) : all; // 0 = all time
  // Tiles follow the selected range, compared with the same number of months just before it.
  const totals = (ms: Month[]) => ({
    income: sum(ms.map((m) => m.income)),
    costs: sum(ms.map(cost)),
    profit: sum(ms.map((m) => m.profit)),
  });
  const total = totals(rows);
  const earlier = periods ? all.slice(0, -periods).slice(-periods) : [];
  const prev = periods && earlier.length === periods ? totals(earlier) : null;
  const margin = num(total.income) > 0 ? (num(total.profit) / num(total.income)) * 100 : null;
  const span = periods ? `last ${rows.length} month${rows.length === 1 ? "" : "s"}` : `all time (${rows.length} month${rows.length === 1 ? "" : "s"})`;
  const soFar = rows.at(-1)?.in_progress ? `Includes ${rows.at(-1)!.label} so far` : undefined;
  const trend = (f: (m: Month) => string) => rows.map((m) => num(f(m)));
  const vsPrev = periods === 12 ? "vs the year before" : periods === 24 ? "vs the 2 years before" : `vs previous ${periods} months`;
  const base = r?.base_currency ?? "";
  // What the selected employees paid their hires in the range. It's already part of their expenses.
  const hirePay = [...rows.flatMap((m) => m.hire_payments ?? []).reduce((byHire, p) => {
    const seen = byHire.get(p.hire_id);
    return byHire.set(p.hire_id, { name: p.hire_name, amount: sum([seen?.amount ?? "0", p.amount]) });
  }, new Map<string, { name: string; amount: string }>())].map(([id, x]) => ({ id, ...x }));
  const showHires = emp && hirePay.length > 0;

  const chartData = rows.map((m) => ({
    label: shortLabel(m.label),
    income: num(m.income),
    expenses: num(m.expenses),
    salary: num(emp ? m.salary_calculated : m.salary_paid),
    profit: num(m.profit),
  }));

  return (
    <>
      <PageHeader
        title={emp ? `Monthly summary · ${picked.length > 3 ? `${picked.length} selected` : picked.join(", ")}` : "Monthly summary"}
        description={
          emp
            ? "Per employee: revenue credited to them, expenses tagged to them plus their share of split expenses, and salary earned. Not assigned: company income and expenses nobody carries. Several selected are added together."
            : "Income, costs and profit per month, where a month is a salary period (Settings → Salary Cycle). Click an amount to see the payments behind it."
        }
        actions={
          <>
            {financial && can("salary.read") && (
              <div className="w-56">
                <OwnerSelect value={selection} onChange={setSelection} />
              </div>
            )}
            <MonthsSelect value={periods} onChange={setPeriods} options={[3, 6, 12, 24, 0]} />
            <ExportMenu path="/reports/monthly-summary" params={{ periods: String(periods), ...params }} />
          </>
        }
      />
      {me.isError ? (
        <EmptyState title="Your sign-in isn't linked to an employee" description="Ask an administrator to link your account to your employee record." />
      ) : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : rows.length === 0 ? (
        <EmptyState title="No months yet" />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label={`${L.income} · ${span}`}
              value={formatAmount(total.income)}
              unit={base}
              hint={soFar}
              delta={prev && <Delta current={num(total.income)} previous={num(prev.income)} suffix={vsPrev} />}
              spark={<Sparkline values={trend((m) => m.income)} color={SERIES[0]} label={`${L.income} per month, ${span}`} />}
            />
            <StatTile
              label={`Costs · ${span}`}
              value={formatAmount(total.costs)}
              unit={base}
              hint={L.costsHint}
              delta={prev && <Delta current={num(total.costs)} previous={num(prev.costs)} suffix={vsPrev} goodWhenUp={false} />}
              spark={<Sparkline values={trend(cost)} color={SERIES[1]} label={`Costs per month, ${span}`} />}
            />
            <StatTile
              label={`${L.profit} · ${span}`}
              value={formatAmount(total.profit)}
              unit={base}
              tone={sign(total.profit) < 0 ? "bad" : undefined}
              hint={margin !== null ? `${margin.toFixed(1)}% margin` : undefined}
              delta={prev && <Delta current={num(total.profit)} previous={num(prev.profit)} suffix={vsPrev} />}
              spark={<Sparkline values={trend((m) => m.profit)} color={SERIES[3]} label={`${L.profit} per month, ${span}`} />}
            />
            <StatTile
              label={`Monthly average · ${span}`}
              value={formatAmount((num(total.profit) / rows.length).toFixed(2))}
              unit={base}
              tone={sign(total.profit) < 0 ? "bad" : undefined}
              hint={`${L.profit} per month on ${formatAmount((num(total.income) / rows.length).toFixed(2))} ${L.income.toLowerCase()}`}
            />
          </div>

          <Card className="mb-6">
            <CardHeader><CardTitle>{L.income}, costs and {L.profit.toLowerCase()}</CardTitle></CardHeader>
            <CardContent>
              <PeriodChart
                label={`${L.income}, expenses, salary and ${L.profit.toLowerCase()} per month`}
                data={chartData}
                unit={base}
                bars={[
                  { key: "income", label: L.income, color: SERIES[0] },
                  { key: "expenses", label: "Expenses", color: SERIES[1], stack: "cost" },
                  { key: "salary", label: L.salary, color: SERIES[2], stack: "cost" },
                ]}
                line={{ key: "profit", label: L.profit, color: SERIES[3] }}
              />
              {rows.at(-1)?.in_progress && <p className="mt-2 text-xs text-muted-foreground">{rows.at(-1)!.label} is still in progress: its figures are so far.</p>}
            </CardContent>
          </Card>

          {showHires && (
            <Card className="mb-6">
              <CardHeader><CardTitle>Hired managers · {span}</CardTitle></CardHeader>
              <CardContent>
                <ul className="flex flex-col gap-1 text-sm">
                  {hirePay.map((h) => (
                    <li key={h.id} className="flex justify-between gap-3">
                      <span>{h.name}</span>
                      <span className="tabular">{formatAmount(h.amount)} {base}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-xs text-muted-foreground">Already included in Expenses above. It comes off revenue before salary is calculated.</p>
              </CardContent>
            </Card>
          )}

          <Card className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Month</TH>
                  <TH className="text-right">{L.income}</TH>
                  <TH className="text-right" title={emp ? "Employees: expenses tagged to them plus their share of split expenses. Not assigned: expenses nobody carries" : undefined}>Expenses</TH>
                  {showHires && <TH className="text-right" title="Paid to hired managers. Already included in Expenses">Of which hired managers</TH>}
                  <TH className="text-right" title={emp ? "Paid toward this month's salary, whenever it was paid" : undefined}>Salary paid</TH>
                  <TH className="text-right" title={emp ? "Revenue − expenses − salary earned: what they leave the company" : undefined}>{L.profit}</TH>
                  <TH className="text-right">Margin</TH>
                  <TH className="text-right" title="Salary earned by employees in the month (paid or not)">Salary earned</TH>
                  {!emp && (
                    <>
                      <TH className="text-right" title="Money that came into bank, cash and wallets">Cash in</TH>
                      <TH className="text-right" title="Money that left bank, cash and wallets">Cash out</TH>
                      <TH className="text-right" title="Bank, cash and wallets at the end of the month, as recorded">Closing cash</TH>
                    </>
                  )}
                </TR>
              </THead>
              <TBody>
                {[...rows].reverse().map((row) => {
                  const range = { from: row.start_date, to: row.end_date, employee_id: drillEmployee };
                  const drillable = canDrill && (!emp || !!drillEmployee);
                  return (
                    <TR key={row.label}>
                      <TD className="whitespace-nowrap">
                        <span className="font-medium">{row.label}</span>{" "}
                        <span className="text-xs text-muted-foreground">{periodRange(row)}{row.in_progress ? " · so far" : row.status === "closed" ? " · closed" : ""}</span>
                      </TD>
                      <TD className="tabular text-right">{drillable ? <DrillAmount value={row.income} drill={{ ...range, direction: "receive" }} /> : formatAmount(row.income)}</TD>
                      <TD className="tabular text-right">{drillable ? <DrillAmount value={row.expenses} drill={{ ...range, direction: "pay" }} /> : formatAmount(row.expenses)}</TD>
                      {showHires && <TD className="tabular text-right text-muted-foreground">{formatAmount(row.hired_manager_pay ?? "0")}</TD>}
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(row.salary_paid)}</TD>
                      <TD className={cn("tabular text-right font-medium", sign(row.profit) < 0 && "text-destructive")}>{formatAmount(row.profit)}</TD>
                      <TD className="text-right"><Margin value={row.margin_pct} /></TD>
                      <TD className="tabular text-right">{formatAmount(row.salary_calculated)}</TD>
                      {!emp && (
                        <>
                          <TD className="tabular text-right">{formatAmount(row.cash_in)}</TD>
                          <TD className="tabular text-right">{formatAmount(row.cash_out)}</TD>
                          <TD className={cn("tabular text-right", sign(row.closing_cash) < 0 && "text-destructive")}>{formatAmount(row.closing_cash)}</TD>
                        </>
                      )}
                    </TR>
                  );
                })}
                <TR className="font-medium">
                  <TD>Total, {rows.length} months ({base})</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.income)))}</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.expenses)))}</TD>
                  {showHires && <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.hired_manager_pay ?? "0")))}</TD>}
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.salary_paid)))}</TD>
                  <TD className={cn("tabular text-right", sign(sum(rows.map((m) => m.profit))) < 0 && "text-destructive")}>{formatAmount(sum(rows.map((m) => m.profit)))}</TD>
                  <TD />
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.salary_calculated)))}</TD>
                  {!emp && (
                    <>
                      <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.cash_in)))}</TD>
                      <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.cash_out)))}</TD>
                      <TD />
                    </>
                  )}
                </TR>
              </TBody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}
