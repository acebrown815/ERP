"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Delta, num, PeriodChart, SERIES, Sparkline, StatTile } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { DrillAmount, MonthsSelect, shortLabel } from "@/components/reports/shared";
import { periodRange } from "@/components/salary/shared";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign, sum } from "@/lib/money";
import type { MonthlySummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Month = MonthlySummary["rows"][number];

const costs = (r: Month) => sum([r.expenses, r.salary_paid]);

function Margin({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  return <span className={cn("tabular", sign(value) < 0 && "text-destructive")}>{value}%</span>;
}

export default function MonthlySummaryPage() {
  const [periods, setPeriods] = useState(12);
  // Always load 24 so year-to-date and comparisons work whatever range is shown.
  const q = useQuery({
    queryKey: ["report-monthly", 24],
    queryFn: () => api.get<MonthlySummary>("/reports/monthly-summary", { periods: 24 }),
    placeholderData: keepPreviousData,
  });
  const r = q.data;
  const all = r?.rows ?? [];
  const rows = all.slice(-periods);
  const done = all.filter((m) => !m.in_progress);
  const last = done.at(-1);
  const before = done.at(-2);
  const year = new Date().getFullYear();
  const ytd = all.filter((m) => m.start_date.startsWith(String(year)));
  const ytdIncome = sum(ytd.map((m) => m.income));
  const ytdProfit = sum(ytd.map((m) => m.profit));
  const trend = (f: (m: Month) => string) => done.slice(-6).map((m) => num(f(m)));
  const base = r?.base_currency ?? "";

  const chartData = rows.map((m) => ({
    label: shortLabel(m.label),
    income: num(m.income),
    expenses: num(m.expenses),
    salary: num(m.salary_paid),
    profit: num(m.profit),
  }));

  return (
    <>
      <PageHeader
        title="Monthly summary"
        description="Income, costs and profit per month, where a month is a salary period (Settings → Salary Cycle). Click an amount to see the payments behind it."
        actions={
          <>
            <MonthsSelect value={periods} onChange={setPeriods} />
            <ExportMenu path="/reports/monthly-summary" params={{ periods: String(periods) }} />
          </>
        }
      />
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : rows.length === 0 ? (
        <EmptyState title="No months yet" />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label={last ? `Income · ${last.label}` : "Income"}
              value={last ? formatAmount(last.income) : "—"}
              unit={base}
              delta={last && <Delta current={num(last.income)} previous={before ? num(before.income) : null} />}
              spark={<Sparkline values={trend((m) => m.income)} color={SERIES[0]} label="Income, last 6 months" />}
            />
            <StatTile
              label={last ? `Costs · ${last.label}` : "Costs"}
              value={last ? formatAmount(costs(last)) : "—"}
              unit={base}
              hint="Expenses + salary paid"
              delta={last && <Delta current={num(costs(last))} previous={before ? num(costs(before)) : null} goodWhenUp={false} />}
              spark={<Sparkline values={trend(costs)} color={SERIES[1]} label="Costs, last 6 months" />}
            />
            <StatTile
              label={last ? `Profit · ${last.label}` : "Profit"}
              value={last ? formatAmount(last.profit) : "—"}
              unit={base}
              tone={last && sign(last.profit) < 0 ? "bad" : undefined}
              hint={last?.margin_pct ? `${last.margin_pct}% margin` : undefined}
              delta={last && <Delta current={num(last.profit)} previous={before ? num(before.profit) : null} />}
              spark={<Sparkline values={trend((m) => m.profit)} color={SERIES[3]} label="Profit, last 6 months" />}
            />
            <StatTile
              label={`Year to date · ${year}`}
              value={formatAmount(ytdProfit)}
              unit={base}
              tone={sign(ytdProfit) < 0 ? "bad" : undefined}
              hint={`Profit on ${formatAmount(ytdIncome)} income · ${ytd.length} month${ytd.length === 1 ? "" : "s"}`}
            />
          </div>

          <Card className="mb-6">
            <CardHeader><CardTitle>Income, costs and profit</CardTitle></CardHeader>
            <CardContent>
              <PeriodChart
                label="Income, expenses, salary and profit per month"
                data={chartData}
                unit={base}
                bars={[
                  { key: "income", label: "Income", color: SERIES[0] },
                  { key: "expenses", label: "Expenses", color: SERIES[1], stack: "cost" },
                  { key: "salary", label: "Salary paid", color: SERIES[2], stack: "cost" },
                ]}
                line={{ key: "profit", label: "Profit", color: SERIES[3] }}
              />
              {rows.at(-1)?.in_progress && <p className="mt-2 text-xs text-muted-foreground">{rows.at(-1)!.label} is still in progress: its figures are so far.</p>}
            </CardContent>
          </Card>

          <Card className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH>Month</TH>
                  <TH className="text-right">Income</TH>
                  <TH className="text-right">Expenses</TH>
                  <TH className="text-right">Salary paid</TH>
                  <TH className="text-right">Profit</TH>
                  <TH className="text-right">Margin</TH>
                  <TH className="text-right" title="Salary earned by employees in the month (paid or not)">Salary earned</TH>
                  <TH className="text-right" title="Money that came into bank, cash and wallets">Cash in</TH>
                  <TH className="text-right" title="Money that left bank, cash and wallets">Cash out</TH>
                  <TH className="text-right" title="Bank, cash and wallets at the end of the month, as recorded">Closing cash</TH>
                </TR>
              </THead>
              <TBody>
                {[...rows].reverse().map((row) => {
                  const range = { from: row.start_date, to: row.end_date };
                  return (
                    <TR key={row.label}>
                      <TD className="whitespace-nowrap">
                        <span className="font-medium">{row.label}</span>{" "}
                        <span className="text-xs text-muted-foreground">{periodRange(row)}{row.in_progress ? " · so far" : row.status === "closed" ? " · closed" : ""}</span>
                      </TD>
                      <TD className="tabular text-right"><DrillAmount value={row.income} drill={{ ...range, direction: "receive" }} /></TD>
                      <TD className="tabular text-right"><DrillAmount value={row.expenses} drill={{ ...range, direction: "pay" }} /></TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(row.salary_paid)}</TD>
                      <TD className={cn("tabular text-right font-medium", sign(row.profit) < 0 && "text-destructive")}>{formatAmount(row.profit)}</TD>
                      <TD className="text-right"><Margin value={row.margin_pct} /></TD>
                      <TD className="tabular text-right">{formatAmount(row.salary_calculated)}</TD>
                      <TD className="tabular text-right">{formatAmount(row.cash_in)}</TD>
                      <TD className="tabular text-right">{formatAmount(row.cash_out)}</TD>
                      <TD className={cn("tabular text-right", sign(row.closing_cash) < 0 && "text-destructive")}>{formatAmount(row.closing_cash)}</TD>
                    </TR>
                  );
                })}
                <TR className="font-medium">
                  <TD>Total, {rows.length} months ({base})</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.income)))}</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.expenses)))}</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.salary_paid)))}</TD>
                  <TD className={cn("tabular text-right", sign(sum(rows.map((m) => m.profit))) < 0 && "text-destructive")}>{formatAmount(sum(rows.map((m) => m.profit)))}</TD>
                  <TD />
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.salary_calculated)))}</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.cash_in)))}</TD>
                  <TD className="tabular text-right">{formatAmount(sum(rows.map((m) => m.cash_out)))}</TD>
                  <TD />
                </TR>
              </TBody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}
