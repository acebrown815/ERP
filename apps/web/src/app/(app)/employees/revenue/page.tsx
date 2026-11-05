"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { DateRange, useReportRange } from "@/components/accounting/report-controls";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { periodRange } from "@/components/salary/shared";
import { Card } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import { useCompany } from "@/lib/queries";
import type { RevenueReport } from "@/lib/types";

export default function RevenueContributionsPage() {
  const base = useCompany().data?.base_currency ?? "USD";
  const { range, setRange, ready } = useReportRange("last_6");
  const q = useQuery({
    queryKey: ["report-employee-revenue", range],
    queryFn: () => api.get<RevenueReport>("/reports/employee-revenue", range),
    placeholderData: keepPreviousData,
    enabled: ready,
  });
  const r = q.data;
  return (
    <>
      <PageHeader
        title="Revenue contributions"
        description={`Net revenue per employee per salary period (${base}): customer payments split to them, minus expenses tagged to them. Periods follow the salary cycle (Settings → Salary Cycle), not calendar months.`}
        actions={
          <>
            <DateRange {...range} onChange={setRange} wholePeriods />
            <ExportMenu path="/reports/employee-revenue" params={range} />
          </>
        }
      />
      <Card className="overflow-x-auto">
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
          <EmptyState title="No revenue credited in these periods" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Employee</TH>
                {r.periods.map((p) => (
                  <TH key={p.id} className="text-right">
                    <span className="block">{p.label}</span>
                    <span className="block text-[11px] font-normal normal-case tracking-normal">{periodRange(p)}</span>
                  </TH>
                ))}
                <TH className="text-right">Total</TH>
              </TR>
            </THead>
            <TBody>
              {r.rows.map((row) => (
                <TR key={row.employee_id}>
                  <TD><Link href={`/employees/${row.employee_id}`} className="font-medium hover:underline">{row.employee_name}</Link></TD>
                  {row.by_period.map((v, i) => (
                    <TD key={i} className="text-right align-top">
                      <span className={`tabular block ${sign(v) < 0 ? "text-destructive" : sign(v) ? "" : "text-muted-foreground"}`}>{formatAmount(v)}</span>
                      {sign(row.expenses_by_period[i]) !== 0 && (
                        <span className="tabular block text-xs text-muted-foreground">
                          {formatAmount(row.gross_by_period[i])} − {formatAmount(row.expenses_by_period[i])}
                        </span>
                      )}
                    </TD>
                  ))}
                  <TD className={`tabular text-right font-medium ${sign(row.total) < 0 ? "text-destructive" : ""}`}>{formatAmount(row.total)}</TD>
                </TR>
              ))}
              <TR className="font-medium">
                <TD>Total</TD>
                {r.totals.map((v, i) => <TD key={i} className="tabular text-right">{formatAmount(v)}</TD>)}
                <TD className="tabular text-right">{formatAmount(r.total)}</TD>
              </TR>
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
