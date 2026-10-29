"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { periodRange } from "@/components/salary/shared";
import { Select } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import type { MonthlySummary } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Simple SVG bars: income vs expenses + salary per month (display only). */
function Bars({ rows }: { rows: MonthlySummary["rows"] }) {
  const max = Math.max(1, ...rows.map((r) => Math.max(Number(r.income), Number(r.expenses) + Number(r.salary_paid))));
  return (
    <div className="flex h-40 items-end gap-2 overflow-x-auto px-4 pb-2 pt-4" role="img" aria-label="Income and costs per month">
      {rows.map((r) => (
        <div key={r.label} className="flex min-w-12 flex-1 flex-col items-center gap-1">
          <div className="flex h-32 w-full items-end justify-center gap-0.5">
            <div className="w-1/2 rounded-t bg-primary/70" style={{ height: `${(Number(r.income) / max) * 100}%` }} title={`Income ${formatAmount(r.income)}`} />
            <div className="flex w-1/2 flex-col justify-end" style={{ height: `${((Number(r.expenses) + Number(r.salary_paid)) / max) * 100}%` }}>
              <div className="rounded-t bg-orange-400/70" style={{ flex: Number(r.salary_paid) || 0.0001 }} title={`Salary ${formatAmount(r.salary_paid)}`} />
              <div className="bg-slate-400/70" style={{ flex: Number(r.expenses) || 0.0001 }} title={`Expenses ${formatAmount(r.expenses)}`} />
            </div>
          </div>
          <span className="text-[11px] text-muted-foreground">{r.label.replace(" (transition)", "*")}</span>
        </div>
      ))}
    </div>
  );
}

export default function MonthlySummaryPage() {
  const [periods, setPeriods] = useState(12);
  const q = useQuery({
    queryKey: ["report-monthly", periods],
    queryFn: () => api.get<MonthlySummary>("/reports/monthly-summary", { periods }),
    placeholderData: keepPreviousData,
  });
  const r = q.data;
  const rows = [...(r?.rows ?? [])];
  return (
    <>
      <PageHeader
        title="Monthly summary"
        description="Income, expenses, salary and profit per month, where a month is a salary period (Settings → Salary Cycle)."
        actions={
          <>
            <Select aria-label="Months" className="w-36" value={periods} onChange={(e) => setPeriods(Number(e.target.value))}>
              {[3, 6, 12, 24].map((n) => <option key={n} value={n}>Last {n} months</option>)}
            </Select>
            <ExportMenu path="/reports/monthly-summary" params={{ periods: String(periods) }} />
          </>
        }
      />
      <Card className="overflow-x-auto">
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : rows.length === 0 ? (
          <EmptyState title="No months yet" />
        ) : (
          <>
            <Bars rows={rows} />
            <p className="flex gap-4 px-4 pb-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-primary/70" /> Income</span>
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-slate-400/70" /> Expenses</span>
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-orange-400/70" /> Salary paid</span>
            </p>
            <Table>
              <THead>
                <TR>
                  <TH>Month</TH>
                  <TH className="text-right">Income</TH>
                  <TH className="text-right">Expenses</TH>
                  <TH className="text-right">Salary paid</TH>
                  <TH className="text-right">Profit</TH>
                  <TH className="text-right" title="Salary earned by employees in the month (paid or not)">Salary earned</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <TR key={row.label}>
                    <TD><span className="font-medium">{row.label}</span> <span className="text-xs text-muted-foreground">{periodRange(row)}{row.status === "closed" ? " · closed" : ""}</span></TD>
                    <TD className="tabular text-right">{formatAmount(row.income)}</TD>
                    <TD className="tabular text-right text-muted-foreground">{formatAmount(row.expenses)}</TD>
                    <TD className="tabular text-right text-muted-foreground">{formatAmount(row.salary_paid)}</TD>
                    <TD className={cn("tabular text-right font-medium", sign(row.profit) < 0 && "text-destructive")}>{formatAmount(row.profit)}</TD>
                    <TD className="tabular text-right">{formatAmount(row.salary_calculated)}</TD>
                  </TR>
                ))}
                {r.totals && (
                  <TR className="font-medium">
                    <TD>Total ({r.base_currency})</TD>
                    <TD className="tabular text-right">{formatAmount(r.totals.income)}</TD>
                    <TD className="tabular text-right">{formatAmount(r.totals.expenses)}</TD>
                    <TD className="tabular text-right">{formatAmount(r.totals.salary_paid)}</TD>
                    <TD className={cn("tabular text-right", sign(r.totals.profit) < 0 && "text-destructive")}>{formatAmount(r.totals.profit)}</TD>
                    <TD className="tabular text-right">{formatAmount(r.totals.salary_calculated)}</TD>
                  </TR>
                )}
              </TBody>
            </Table>
          </>
        )}
      </Card>
    </>
  );
}
