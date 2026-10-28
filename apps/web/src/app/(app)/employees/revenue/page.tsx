"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { PeriodRange, rangeQuery, type Range } from "@/components/salary/period-range";
import { periodRange } from "@/components/salary/shared";
import { Card } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import { useCompany, useSalaryPeriods } from "@/lib/queries";
import type { RevenueReport } from "@/lib/types";

export default function RevenueContributionsPage() {
  const base = useCompany().data?.base_currency ?? "USD";
  const periods = useSalaryPeriods();
  const [range, setRange] = useState<Range>({});
  const q = useQuery({
    queryKey: ["report-employee-revenue", range],
    queryFn: () => api.get<RevenueReport>("/reports/employee-revenue", rangeQuery(range)),
  });
  const r = q.data;
  return (
    <>
      <PageHeader
        title="Revenue contributions"
        description={`Customer payments credited to each employee per salary period (${base}). Each payment is split once, so the total equals revenue received, never double-counted.`}
        actions={periods.data && <PeriodRange periods={periods.data} value={range} onChange={setRange} csvPath="/reports/employee-revenue" />}
      />
      <Card className="overflow-x-auto">
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
          <EmptyState title="No revenue credited in these periods" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Employee</TH>
                {r.periods.map((p) => <TH key={p.id} className="text-right" title={periodRange(p)}>{p.label}</TH>)}
                <TH className="text-right">Total</TH>
              </TR>
            </THead>
            <TBody>
              {r.rows.map((row) => (
                <TR key={row.employee_id}>
                  <TD><Link href={`/employees/${row.employee_id}`} className="font-medium hover:underline">{row.employee_name}</Link></TD>
                  {row.by_period.map((v, i) => (
                    <TD key={i} className={`tabular text-right ${sign(v) ? "" : "text-muted-foreground"}`}>{formatAmount(v)}</TD>
                  ))}
                  <TD className="tabular text-right font-medium">{formatAmount(row.total)}</TD>
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
