"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { num, PeriodChart, SERIES } from "@/components/charts/charts";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { ExportMenu } from "@/components/erp/export-menu";
import { PROJECT_STATUS } from "@/components/projects/project-dialog";
import { ProgressBar } from "@/components/projects/shared";
import { Select } from "@/components/ui/input";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sign, sum } from "@/lib/money";
import type { ProjectFinancials } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function ProjectFinancialsPage() {
  const [status, setStatus] = useState("");
  const q = useQuery({
    queryKey: ["project-profitability", status],
    queryFn: () => api.get<ProjectFinancials[]>("/reports/project-profitability", { status: status || undefined }),
  });
  const rows = q.data ?? [];
  const total = (k: "revenue" | "direct_expenses" | "salary_paid" | "profit_cash" | "salary_owed" | "profit_incl_owed") => sum(rows.map((r) => r[k]));
  return (
    <>
      <PageHeader
        title="Project financials"
        description="Profit per project from the ledger: revenue received minus direct expenses and salary paid. Salary earned but not yet paid is shown separately."
        actions={
          <>
            <Select aria-label="Status" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {Object.entries(PROJECT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </Select>
            <ExportMenu path="/reports/project-profitability" params={{ status: status || undefined }} />
          </>
        }
      />
      {rows.some((r) => sign(r.revenue) || sign(r.direct_expenses) || sign(r.salary_paid)) && (
        <Card className="mb-6">
          <CardHeader><CardTitle>Profit by project</CardTitle><CardDescription>Most profitable first (cash basis).</CardDescription></CardHeader>
          <CardContent>
            <PeriodChart
              label="Revenue, costs and profit per project"
              xKey="name"
              data={rows.slice(0, 12).map((r) => ({ name: r.name.length > 18 ? `${r.name.slice(0, 17)}…` : r.name, revenue: num(r.revenue), costs: num(r.budget_used), profit: num(r.profit_cash) }))}
              unit={rows[0]?.base_currency}
              bars={[
                { key: "revenue", label: "Revenue", color: SERIES[0] },
                { key: "costs", label: "Expenses + salary paid", color: SERIES[1] },
                { key: "profit", label: "Profit", color: SERIES[2] },
              ]}
            />
            {rows.length > 12 && <p className="mt-2 text-xs text-muted-foreground">Top 12 of {rows.length}; all are in the table.</p>}
          </CardContent>
        </Card>
      )}
      <Card className="overflow-x-auto">
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <TableSkeleton /> : (
          <Table>
            <THead>
              <TR>
                <TH>Project</TH>
                <TH className="text-right">Revenue</TH>
                <TH className="text-right">Expenses</TH>
                <TH className="text-right">Salary paid</TH>
                <TH className="text-right">Profit (cash)</TH>
                <TH className="text-right">Salary owed</TH>
                <TH className="text-right">Profit after owed</TH>
                <TH className="text-right">Budget left</TH>
                <TH className="text-right" title="Hours logged on tasks, and share of the estimate">Hours</TH>
                <TH className="text-right">Revenue / hour</TH>
                <TH>Progress</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((r) => (
                <TR key={r.project_id}>
                  <TD>
                    <Link href={`/projects/${r.project_id}?tab=financials`} className="font-medium hover:underline">{r.name}</Link>
                    <span className="block text-xs text-muted-foreground">
                      {r.number}{r.customer_name ? ` · ${r.customer_name}` : ""} · <Badge variant={PROJECT_STATUS[r.status]?.variant}>{PROJECT_STATUS[r.status]?.label}</Badge>
                    </span>
                  </TD>
                  <TD className="tabular text-right">{formatAmount(r.revenue)}</TD>
                  <TD className="tabular text-right text-muted-foreground">{formatAmount(r.direct_expenses)}</TD>
                  <TD className="tabular text-right text-muted-foreground">{formatAmount(r.salary_paid)}</TD>
                  <TD className={cn("tabular text-right font-medium", sign(r.profit_cash) < 0 && "text-destructive")}>
                    {formatAmount(r.profit_cash)}
                    {r.margin_pct != null && <span className="block text-xs font-normal text-muted-foreground">{r.margin_pct}%</span>}
                  </TD>
                  <TD className="tabular text-right text-muted-foreground">{formatAmount(r.salary_owed)}</TD>
                  <TD className={cn("tabular text-right", sign(r.profit_incl_owed) < 0 && "text-destructive")}>{formatAmount(r.profit_incl_owed)}</TD>
                  <TD className={cn("tabular text-right", r.budget_remaining != null && sign(r.budget_remaining) < 0 && "text-destructive")}>
                    {r.budget_remaining != null ? formatAmount(r.budget_remaining) : "—"}
                  </TD>
                  <TD className="tabular whitespace-nowrap text-right">
                    {sign(r.logged_hours) ? formatAmount(r.logged_hours, 1) : "—"}
                    {r.hours_used_pct && <span className={cn("block text-xs", Number(r.hours_used_pct) > 100 ? "text-destructive" : "text-muted-foreground")}>{r.hours_used_pct}% of estimate</span>}
                  </TD>
                  <TD className="tabular text-right">{r.revenue_per_hour ? formatAmount(r.revenue_per_hour) : "—"}</TD>
                  <TD className="w-36"><ProgressBar value={r.completion_pct} /></TD>
                </TR>
              ))}
              {rows.length > 1 && (
                <TR className="font-medium">
                  <TD>Total ({rows[0]?.base_currency})</TD>
                  <TD className="tabular text-right">{formatAmount(total("revenue"))}</TD>
                  <TD className="tabular text-right">{formatAmount(total("direct_expenses"))}</TD>
                  <TD className="tabular text-right">{formatAmount(total("salary_paid"))}</TD>
                  <TD className="tabular text-right">{formatAmount(total("profit_cash"))}</TD>
                  <TD className="tabular text-right">{formatAmount(total("salary_owed"))}</TD>
                  <TD className="tabular text-right">{formatAmount(total("profit_incl_owed"))}</TD>
                  <TD />
                  <TD />
                  <TD />
                  <TD />
                </TR>
              )}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
