"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { DateRange, useReportRange } from "@/components/accounting/report-controls";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { periodRange, SalaryStatus } from "@/components/salary/shared";
import { Card } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import { useCompany } from "@/lib/queries";
import type { SalaryReport } from "@/lib/types";

export default function EmployeeSalaryReportPage() {
  const base = useCompany().data?.base_currency ?? "USD";
  const { range, setRange, ready } = useReportRange("last_6");
  const q = useQuery({
    queryKey: ["report-employee-salary", range],
    queryFn: () => api.get<SalaryReport>("/reports/employee-salary", range),
    placeholderData: keepPreviousData,
    enabled: ready,
  });
  const r = q.data;
  return (
    <>
      <PageHeader
        title="Employee salary report"
        description={`Revenue, calculated salary and salary paid per employee and salary period (${base}). Balance is all periods to date.`}
        actions={
          <>
            <DateRange {...range} onChange={setRange} wholePeriods />
            <ExportMenu path="/reports/employee-salary" params={range} />
          </>
        }
      />
      <Card className="overflow-x-auto">
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
          <EmptyState title="No salary in these periods" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Employee</TH>
                {r.periods.map((p) => (
                  <TH key={p.id} className="text-right">
                    <span className="block">{p.label}{p.status === "closed" ? " ✓" : ""}</span>
                    <span className="block text-[11px] font-normal normal-case tracking-normal">{periodRange(p)}</span>
                  </TH>
                ))}
                <TH className="text-right">Calculated</TH>
                <TH className="text-right">Paid</TH>
                <TH className="text-right">Balance</TH>
              </TR>
            </THead>
            <TBody>
              {r.rows.map((row) => (
                <TR key={row.employee_id}>
                  <TD><Link href={`/employees/${row.employee_id}`} className="font-medium hover:underline">{row.employee_name}</Link></TD>
                  {row.by_period.map((c, i) => (
                    <TD key={i} className="text-right align-top">
                      {c ? (
                        <div className="flex flex-col items-end gap-0.5">
                          <span className="tabular font-medium">{formatAmount(c.calculated)}</span>
                          <span className="tabular text-xs text-muted-foreground">
                            on {formatAmount(c.revenue)} net{sign(c.expenses) ? ` (${formatAmount(c.gross_revenue)} − ${formatAmount(c.expenses)})` : ""}
                          </span>
                          <SalaryStatus status={c.status} />
                        </div>
                      ) : <span className="text-muted-foreground">—</span>}
                    </TD>
                  ))}
                  <TD className="tabular text-right">{formatAmount(row.calculated)}</TD>
                  <TD className="tabular text-right">{formatAmount(row.paid)}</TD>
                  <TD className={`tabular text-right ${sign(row.balance) > 0 ? "font-semibold" : "text-muted-foreground"}`}>{formatAmount(row.balance)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <p className="mt-3 text-xs text-muted-foreground">✓ = closed period (final). Open periods show projected figures.</p>
    </>
  );
}
