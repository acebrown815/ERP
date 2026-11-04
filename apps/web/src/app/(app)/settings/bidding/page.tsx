"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleX, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { ConnectionSettings } from "@/components/bidding/connections";
import { ProfileNamesEditor } from "@/components/bidding/employee-view";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { SourceState, Sources } from "@/lib/bidding";
import { formatDate, formatDateTime } from "@/lib/utils";

function SourceCard({ title, state, env, children }: { title: string; state: SourceState; env: string; children: ReactNode }) {
  const Icon = !state.configured ? CircleAlert : state.error ? CircleX : CircleCheck;
  const tone = !state.configured ? "text-warning" : state.error ? "text-destructive" : "text-success";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Icon className={`size-4 ${tone}`} aria-hidden /> {title}</CardTitle>
        <CardDescription>
          {!state.configured ? `Not connected: fill in ${env} above and save.` : state.error ? state.error : `Last read ${formatDateTime(state.fetched_at)}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm">{children}</CardContent>
    </Card>
  );
}

export default function BiddingSheetsPage() {
  const qc = useQueryClient();
  const sources = useQuery({ queryKey: ["bidding", "sources"], queryFn: () => api.get<Sources>("/bidding/sources") });
  const refresh = useMutation({
    mutationFn: () => api.get<Sources>("/bidding/sources", { refresh: true }),
    onSuccess: (data) => {
      qc.setQueryData(["bidding", "sources"], data);
      qc.invalidateQueries({ queryKey: ["bidding"] });
    },
    onError: () => toast.error("Could not refresh"),
  });
  const s = sources.data;

  return (
    <>
      <PageHeader
        title="Bidding sheets"
        description={
          <>
            The ERP reads two Google Sheets live through their Apps Script web apps and stores no bid or job data. Each employee&apos;s bidding profile names must match their tabs in the bids sheet (the extension&apos;s Sheet Tab Name). One employee can have several.
          </>
        }
        actions={<Button variant="outline" loading={refresh.isPending} onClick={() => refresh.mutate()}>{!refresh.isPending && <RefreshCw />} Read sheets now</Button>}
      />
      <h2 className="mb-3 text-lg font-semibold">Connections</h2>
      <ConnectionSettings />
      <h2 className="mb-3 text-lg font-semibold">Status</h2>
      {sources.isError ? <ErrorState error={sources.error} onRetry={() => sources.refetch()} /> : !s ? <TableSkeleton /> : (
        <>
          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <SourceCard title="Bids sheet (BidExtension)" state={s.data.bids} env="the web app URL and shared secret">
              {s.tabs.length} tabs · {s.tabs.reduce((n, t) => n + t.applied, 0)} applied
              {s.unclaimed_tabs.length > 0 && <p className="mt-1 text-warning">Not linked to anyone: {s.unclaimed_tabs.join(", ")}</p>}
            </SourceCard>
            <SourceCard title="Job list (job-scraper)" state={s.data.jobs} env="the web app URL and token">
              {s.job_tabs.map((t) => `${t.name} (${t.rows})`).join(" · ") || "No tabs read"}
              {s.data.job_list_from && <p className="mt-1 text-muted-foreground">Oldest job still in the list: {formatDate(s.data.job_list_from)}</p>}
            </SourceCard>
          </div>
          <p className="mb-6 text-xs text-muted-foreground">Pages reuse what was read for {Math.round(s.cache_seconds / 60)} minutes, or until someone clicks Refresh.</p>

          <div className="grid gap-6 xl:grid-cols-2">
            <Card className="overflow-x-auto">
              <CardHeader><CardTitle>Tabs in the bids sheet</CardTitle></CardHeader>
              <Table>
                <THead>
                  <TR><TH>Tab</TH><TH>Employee</TH><TH className="text-right">Applied</TH><TH>Last bid</TH></TR>
                </THead>
                <TBody>
                  {s.tabs.map((t) => (
                    <TR key={t.name}>
                      <TD className="font-medium">{t.name}</TD>
                      <TD>{t.employee_id ? <Link href={`/bidding/employee?id=${t.employee_id}`} className="hover:underline">{t.employee_name}</Link> : <Badge variant="warning">Unclaimed</Badge>}</TD>
                      <TD className="tabular text-right">{t.applied}</TD>
                      <TD className="text-muted-foreground">{t.last_date ? formatDate(t.last_date) : "—"}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </Card>
            <Card className="overflow-x-auto">
              <CardHeader>
                <CardTitle>Bidding profile names</CardTitle>
                <CardDescription>One employee can have several; their bids are added together on the Bidding pages. Employees can also set their own on My Bidding → Profile.</CardDescription>
              </CardHeader>
              <Table>
                <THead><TR><TH>Employee</TH><TH>Profile names</TH></TR></THead>
                <TBody>
                  {s.employees.map((p) => (
                    <TR key={p.employee_id}>
                      <TD className="align-top font-medium">{p.name}</TD>
                      <TD>
                        <ProfileNamesEditor
                          compact
                          employeeId={p.employee_id}
                          employeeName={p.name}
                          names={p.profile_names}
                          available={s.unclaimed_tabs}
                          missing={s.profiles_without_tab.find((x) => x.employee_id === p.employee_id)?.profile_names}
                          path={`/bidding/employees/${p.employee_id}/profile`}
                        />
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
