"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { monthRange } from "@/components/accounting/report-controls";
import { PROJECT_STATUS } from "@/components/projects/project-dialog";
import { ProgressBar } from "@/components/projects/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import type { Page, PaymentEntry, Project, TaskProgress } from "@/lib/types";
import { formatDate } from "@/lib/utils";

type PaymentTotals = { count: number; paid: string; base_currency: string };

function Tile({ label, value, tone, unit }: { label: string; value: string | number | undefined; tone?: "bad"; unit?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        {value === undefined ? <Skeleton className="mt-1 h-8 w-20" /> : (
          <p className={`tabular mt-1 text-2xl font-semibold ${tone === "bad" ? "text-destructive" : ""}`}>
            {value} {unit && <span className="text-sm font-normal text-muted-foreground">{unit}</span>}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** The dashboard for restricted access: their own work and pay. The API limits every one of these to what is theirs. */
export function HireOverview() {
  const month = monthRange();
  const projects = useQuery({
    queryKey: ["projects", "hire-dashboard"],
    queryFn: async () => (await api.get<Page<Project>>("/projects", { page_size: 100 })).items,
  });
  const ids = projects.data?.map((p) => p.id) ?? [];
  const progress = useQuery({
    queryKey: ["task-progress", ids],
    queryFn: () => api.get<TaskProgress[]>(`/tasks/progress?${new URLSearchParams(ids.map((id) => ["project_ids", id]))}`),
    enabled: ids.length > 0,
  });
  const totals = useQuery({
    queryKey: ["payment-entries", "hire-month", month],
    queryFn: () => api.get<PaymentTotals>("/payment-entries/totals", { from: month.from, to: month.to }),
  });
  const payments = useQuery({
    queryKey: ["payment-entries", "hire-recent"],
    queryFn: async () => (await api.get<Page<PaymentEntry>>("/payment-entries", { page_size: 6 })).items,
  });

  const known = projects.data?.length === 0 || !!progress.data;
  const rows = progress.data ?? [];
  const open = known ? rows.reduce((n, p) => n + p.total - p.done, 0) : undefined;
  const overdue = known ? rows.reduce((n, p) => n + p.overdue, 0) : undefined;
  const active = projects.data?.filter((p) => p.status === "active").length;

  return (
    <>
      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label="Open tasks" value={open} />
        <Tile label="Overdue tasks" value={overdue} tone={overdue ? "bad" : undefined} />
        <Tile label="Active projects" value={active} />
        <Tile label="Paid this month" value={totals.data ? formatAmount(totals.data.paid) : undefined} unit={totals.data?.base_currency} />
      </div>

      <Card className="mb-6">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>My projects</CardTitle>
          <Button variant="ghost" size="sm" asChild><Link href="/projects">All <ArrowRight /></Link></Button>
        </CardHeader>
        <CardContent>
          {!projects.data ? <Skeleton className="h-16 w-full" /> : projects.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No projects yet. A project appears here once you&apos;ve been connected to it.</p>
          ) : (
            <Table>
              <THead><TR><TH>Project</TH><TH>Project manager</TH><TH>Progress</TH><TH className="text-right">Open tasks</TH><TH>Deadline</TH><TH>Status</TH></TR></THead>
              <TBody>
                {projects.data.map((p) => {
                  const prog = rows.find((x) => x.project_id === p.id);
                  return (
                    <TR key={p.id}>
                      <TD><Link href={`/projects/${p.id}`} className="font-medium hover:underline">{p.name}</Link></TD>
                      <TD className="text-sm">{p.manager_name ?? "—"}</TD>
                      <TD><div className="w-32"><ProgressBar value={p.completion_override ?? prog?.percent ?? "0"} /></div></TD>
                      <TD className="tabular text-right text-sm">{prog ? prog.total - prog.done : 0}</TD>
                      <TD className="text-sm">{formatDate(p.deadline)}</TD>
                      <TD><Badge variant={PROJECT_STATUS[p.status]?.variant}>{PROJECT_STATUS[p.status]?.label}</Badge></TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Recent payments</CardTitle>
          <Button variant="ghost" size="sm" asChild><Link href="/accounting/payment-entries">All <ArrowRight /></Link></Button>
        </CardHeader>
        <CardContent>
          {!payments.data ? <Skeleton className="h-16 w-full" /> : payments.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No payments yet.</p>
          ) : (
            <Table>
              <THead><TR><TH>Date</TH><TH>Project</TH><TH className="text-right">Amount</TH><TH>Reference</TH></TR></THead>
              <TBody>
                {payments.data.map((pe) => (
                  <TR key={pe.id}>
                    <TD className="text-sm"><Link href={`/accounting/payment-entries/${pe.id}`} className="hover:underline">{formatDate(pe.posting_date)}</Link></TD>
                    <TD className="text-sm">{pe.project_name ?? "—"}</TD>
                    <TD className="tabular text-right text-sm">{formatAmount(pe.amount)} {pe.currency}</TD>
                    <TD className="text-sm">{pe.reference_no ?? "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
