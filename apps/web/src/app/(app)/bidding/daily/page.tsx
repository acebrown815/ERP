"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { DataBar, RangePicker, ResumeList, Score } from "@/components/bidding/shared";
import { StatTile } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Card } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { lastDays, type Daily, type Range } from "@/lib/bidding";
import { formatDate } from "@/lib/utils";

export default function DailyReportPage() {
  const [range, setRange] = useState<Range>(() => lastDays(1));
  const q = useQuery({
    queryKey: ["bidding", "daily", range],
    queryFn: () => api.get<Daily>("/bidding/daily", { date_from: range.from, date_to: range.to }),
    placeholderData: keepPreviousData,
  });
  const r = q.data;
  const period = r && (r.date_from === r.date_to ? formatDate(r.date_from) : `${formatDate(r.date_from)} – ${formatDate(r.date_to)}`);

  return (
    <>
      <PageHeader
        title="Daily report"
        description="Who bid how much in a period."
        actions={<ExportMenu path="/bidding/daily/export" params={{ date_from: range.from, date_to: range.to }} />}
      />
      <div className="mb-4"><RangePicker value={range} onChange={setRange} /></div>
      <DataBar data={r?.data} />
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Bids applied" value={r.applied} hint={period} />
            <StatTile label="People bidding" value={r.active_bidders} hint={`of ${r.rows.filter((x) => x.employee_id).length} with a profile name`} />
            <StatTile label="Average match score" value={r.avg_score ?? "—"} />
            <StatTile label="Jobs scraped" value={r.scraped} hint="first seen in this period" />
          </div>
          <Card className="overflow-x-auto">
            {r.rows.length === 0 ? <EmptyState title="Nobody to show" description="Set bidding profile names under Settings → Bidding Sheets." /> : (
              <Table>
                <THead>
                  <TR>
                    <TH>Employee</TH>
                    <TH className="text-right">Applied</TH>
                    <TH className="text-right">From job list</TH>
                    <TH className="text-right">Avg score</TH>
                    <TH className="text-right">Min</TH>
                    <TH className="text-right">Max</TH>
                    <TH>Top resumes</TH>
                  </TR>
                </THead>
                <TBody>
                  {r.rows.map((x) => (
                    <TR key={x.employee_id ?? x.name} className={x.applied === 0 ? "text-muted-foreground" : undefined}>
                      <TD>
                        {x.employee_id ? (
                          <>
                            <Link href={`/bidding/employee?id=${x.employee_id}`} className="font-medium hover:underline">{x.name}</Link>
                            {x.tabs.length > 0 && <div className="text-xs text-muted-foreground">{x.tabs.join(", ")}</div>}
                          </>
                        ) : (
                          <span title="A sheet tab nobody has claimed">{x.name} <span className="text-xs">(unclaimed tab)</span></span>
                        )}
                      </TD>
                      <TD className="tabular text-right font-medium">{x.applied}</TD>
                      <TD className="tabular text-right">{x.applied ? x.in_job_list : "—"}</TD>
                      <TD className="text-right"><Score value={x.avg_score} /></TD>
                      <TD className="text-right"><Score value={x.min_score} /></TD>
                      <TD className="text-right"><Score value={x.max_score} /></TD>
                      <TD><ResumeList resumes={x.resumes} /></TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
