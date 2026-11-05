"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";

import { DateRange, monthRange, type Range } from "@/components/accounting/report-controls";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Badge, Card, CardContent } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, sum } from "@/lib/money";
import { useMe } from "@/lib/session";
import type { HiredManagerRow, HiredManagers } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

function groupByHire(rows: HiredManagerRow[]): { hireId: string; rows: HiredManagerRow[] }[] {
  const groups = new Map<string, HiredManagerRow[]>();
  for (const r of rows) groups.set(r.hire_id, [...(groups.get(r.hire_id) ?? []), r]);
  return [...groups].map(([hireId, group]) => ({ hireId, rows: group }));
}

/** One row per hire and project manager. A manager only ever gets their own rows from the API. */
export default function HiredManagersPage() {
  const me = useMe();
  const everyone = me.permissions["hired_managers.read"] === "all";
  const seesPayments = "payments.create" in me.permissions || "reports.financial" in me.permissions;
  const [range, setRange] = useState<Range>(monthRange());
  const q = useQuery({
    queryKey: ["report-hired-managers", range],
    queryFn: () => api.get<HiredManagers>("/reports/hired-managers", { from: range.from, to: range.to }),
    placeholderData: keepPreviousData,
  });
  const r = q.data;
  return (
    <>
      <PageHeader
        title="Hired managers"
        description={everyone ? "What each hire is doing and being paid, per project manager." : "What your hires are doing and being paid, on your projects."}
        actions={<ExportMenu path="/reports/hired-managers" params={{ from: range.from, to: range.to }} />}
      />
      <Card className="mb-4"><CardContent className="py-4"><DateRange {...range} onChange={setRange} /></CardContent></Card>
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
        <Card><EmptyState title="No hired managers yet" description={everyone ? "Mark someone as a hired manager on their employee record, then select them on a project." : "Select a hire on one of your projects to see their work here."} /></Card>
      ) : (
        <Card>
          <Table>
            <THead>
              <TR>
                <TH>Hire</TH>
                <TH>Project manager</TH>
                <TH className="text-right">Projects</TH>
                <TH className="text-right" title="Created and completed in the selected dates">Tasks done / added</TH>
                <TH className="text-right" title="Right now, whatever the dates">Open</TH>
                <TH className="text-right" title="Right now, whatever the dates">Overdue</TH>
                <TH>Last activity</TH>
                <TH className="text-right">Paid</TH>
                <TH className="text-right" title="Their revenue in the selected dates, after expenses such as this hire">Manager&apos;s net revenue</TH>
              </TR>
            </THead>
            <TBody>
              {groupByHire(r.rows).map(({ hireId, rows }) => (
                <Fragment key={hireId}>
                  {rows.map((row) => (
                    <TR key={`${row.hire_id}-${row.manager_id ?? "none"}`}>
                      <TD>
                        <Link href={`/projects?hire=${row.hire_id}`} className="font-medium hover:underline">{row.hire_name}</Link>
                        {row.hire_status !== "active" && <Badge variant="muted" className="ml-2">{row.hire_status === "terminated" ? "Left" : "On leave"}</Badge>}
                      </TD>
                      <TD className="text-sm">{row.manager_name ?? <span className="text-muted-foreground">No project yet</span>}</TD>
                      <TD className="tabular text-right text-sm">
                        {row.projects}
                      </TD>
                      <TD className="tabular text-right text-sm">{row.tasks_completed} / {row.tasks_created}</TD>
                      <TD className="tabular text-right text-sm">{row.tasks_open}</TD>
                      <TD className={cn("tabular text-right text-sm", row.tasks_overdue > 0 && "font-medium text-destructive")}>{row.tasks_overdue}</TD>
                      <TD className="text-sm">
                        <span className={cn("inline-flex items-center gap-1", row.stale && "font-medium text-destructive")}
                          title={row.stale ? `No activity for ${r.stale_after_days} days or more` : undefined}>
                          {row.stale && <CircleAlert className="size-3.5" aria-label="Inactive" />}
                          {row.last_activity ? formatDate(row.last_activity.slice(0, 10)) : "—"}
                        </span>
                      </TD>
                      <TD className="tabular text-right text-sm">
                        {seesPayments ? <Link href={`/accounting/payment-entries?employee_id=${row.hire_id}`} className="hover:underline">{formatAmount(row.paid)}</Link> : formatAmount(row.paid)}
                      </TD>
                      <TD className="tabular text-right text-sm">
                        {row.manager_id ? formatAmount(row.manager_net_revenue) : "—"}
                        {row.manager_id && <span className="block text-xs text-muted-foreground">of {formatAmount(row.manager_gross_revenue)}</span>}
                      </TD>
                    </TR>
                  ))}
                  {everyone && rows.length > 1 && (
                    <TR className="bg-muted/40">
                      <TD className="text-sm font-medium">{rows[0]!.hire_name} total</TD>
                      <TD />
                      <TD className="tabular text-right text-sm font-medium">{rows.reduce((n, x) => n + x.projects, 0)}</TD>
                      <TD className="tabular text-right text-sm font-medium">{rows.reduce((n, x) => n + x.tasks_completed, 0)} / {rows.reduce((n, x) => n + x.tasks_created, 0)}</TD>
                      <TD className="tabular text-right text-sm font-medium">{rows.reduce((n, x) => n + x.tasks_open, 0)}</TD>
                      <TD className="tabular text-right text-sm font-medium">{rows.reduce((n, x) => n + x.tasks_overdue, 0)}</TD>
                      <TD />
                      <TD className="tabular text-right text-sm font-medium">{formatAmount(sum(rows.map((x) => x.paid)))}</TD>
                      <TD />
                    </TR>
                  )}
                </Fragment>
              ))}
            </TBody>
          </Table>
          <p className="border-t p-3 text-xs text-muted-foreground">Amounts in {r.base_currency}. Flagged when there&apos;s been no activity on the hire&apos;s projects for {r.stale_after_days} days or more.</p>
        </Card>
      )}
    </>
  );
}
