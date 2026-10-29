"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DateRange, usePeriodRanges, type Range } from "@/components/accounting/report-controls";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Card, CardContent } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import type { CategoryReport } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function CategoryReportPage() {
  const periods = usePeriodRanges();
  const [chosen, setRange] = useState<Range | null>(null);
  const range = chosen ?? { from: periods.current.from, to: periods.current.to };
  const [kind, setKind] = useState<"income" | "expense">("expense");
  const q = useQuery({
    queryKey: ["report-by-category", kind, range],
    queryFn: () => api.get<CategoryReport>("/reports/by-category", { kind, from: range.from, to: range.to }),
    placeholderData: keepPreviousData,
    enabled: !!chosen || !periods.loading,
  });
  const r = q.data;
  return (
    <>
      <PageHeader
        title="Income & expenses by category"
        description="What the money came from or went to, per account and category, from the posted ledger."
        actions={<ExportMenu path="/reports/by-category" params={{ kind, from: range.from, to: range.to }} />}
      />
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <div className="flex gap-1 rounded-md border p-0.5 text-sm" role="radiogroup" aria-label="Kind">
            {(["expense", "income"] as const).map((k) => (
              <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
                className={cn("rounded px-3 py-1", kind === k ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground")}>
                {k === "income" ? "Income" : "Expenses"}
              </button>
            ))}
          </div>
          <DateRange {...range} onChange={setRange} />
        </CardContent>
      </Card>
      <Card>
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
          <EmptyState title={`No ${kind === "income" ? "income" : "expenses"} in this range`} />
        ) : (
          <Table>
            <THead><TR><TH>Account</TH><TH>Category</TH><TH className="w-1/3">Share</TH><TH className="text-right">Amount ({r.base_currency})</TH></TR></THead>
            <TBody>
              {r.rows.map((row, i) => (
                <TR key={i}>
                  <TD><span className="font-mono text-xs text-muted-foreground">{row.account_code}</span> {row.account_name}</TD>
                  <TD>{row.category_name ?? <span className="text-muted-foreground">Not categorised</span>}</TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Number(row.share_pct))}%` }} /></div>
                      <span className="tabular w-12 text-right text-xs text-muted-foreground">{row.share_pct}%</span>
                    </div>
                  </TD>
                  <TD className="tabular text-right">{formatAmount(row.amount)}</TD>
                </TR>
              ))}
              <TR className="font-medium"><TD>Total</TD><TD /><TD /><TD className="tabular text-right">{formatAmount(r.total)}</TD></TR>
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
