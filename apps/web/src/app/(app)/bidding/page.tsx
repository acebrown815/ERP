"use client";

import { CalendarCheck, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CountBars, DataBar, DayBars, dayLabel, Heatmap, pct, RangePicker, ResumeList, Score } from "@/components/bidding/shared";
import { SERIES, Sparkline, StatTile } from "@/components/charts/charts";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { lastDays, useSeesAllBids, useStats, type EmployeeRow, type Range } from "@/lib/bidding";
import { formatDate } from "@/lib/utils";

const HEATMAP_DAYS = 14;

function Name({ row }: { row: EmployeeRow }) {
  if (row.employee_id) return <Link href={`/bidding/employee?id=${row.employee_id}`} className="font-medium hover:underline">{row.name}</Link>;
  return <span className="text-muted-foreground" title="A sheet tab nobody has claimed as their bidding profile name">{row.name} <span className="text-xs">(unclaimed tab)</span></span>;
}

export default function BiddingOverviewPage() {
  const all = useSeesAllBids();
  const [range, setRange] = useState<Range>(() => lastDays(30));
  const stats = useStats(range);
  const s = stats.data;

  if (!all) {
    return <EmptyState title="Team numbers are for managers" description="Your own numbers are on My Bidding." action={<Button asChild><Link href="/bidding/me">My Bidding</Link></Button>} />;
  }

  const days = s?.series.map((d) => d.date) ?? [];
  const tail = Math.max(0, days.length - HEATMAP_DAYS);
  const bidders = s?.employees ?? [];

  return (
    <>
      <PageHeader
        title="Team bidding"
        description="Everyone's bids and the scraped job list, read live from the Google Sheets."
        actions={
          <>
            <Button variant="outline" asChild><Link href="/bidding/daily"><CalendarCheck /> Daily report</Link></Button>
            <Button variant="outline" asChild><Link href="/bidding/jobs?status=not_bid"><Search /> Jobs not bid yet</Link></Button>
          </>
        }
      />
      <div className="mb-4"><RangePicker value={range} onChange={setRange} /></div>
      <DataBar data={s?.data} />
      {stats.isError ? <ErrorState error={stats.error} onRetry={() => stats.refetch()} /> : !s ? <TableSkeleton /> : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Bids applied"
              value={s.applied}
              hint={`${s.active_bidders} people bidding`}
              spark={<Sparkline values={s.series.map((d) => d.applied)} label="Bids per day" />}
            />
            <StatTile label="Average match score" value={s.avg_score ?? "—"} hint={s.duplicates ? `${s.duplicates} bids on a job also bid on from another profile` : "No duplicate bids"} />
            <StatTile
              label="Jobs scraped"
              value={s.scraped}
              hint={`first seen ${formatDate(s.date_from)} – ${formatDate(s.date_to)}`}
              spark={<Sparkline values={s.series.map((d) => d.scraped)} color={SERIES[1]} label="Jobs scraped per day" />}
            />
            <StatTile label="Job list covered" value={pct(s.coverage_pct)} hint={`${s.scraped_bid} of ${s.scraped} scraped jobs bid on · ${s.outside_job_list} bids found elsewhere`} />
          </div>

          <div className="mb-6 grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Bids per day</CardTitle><CardDescription>Applied bids, whole team</CardDescription></CardHeader>
              <CardContent>
                <DayBars label="Bids per day" data={s.series.map((d) => ({ label: dayLabel(d.date), applied: d.applied }))} bars={[{ key: "applied", label: "Applied", color: SERIES[0] }]} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Jobs scraped per day</CardTitle><CardDescription>By first-seen date in the job list</CardDescription></CardHeader>
              <CardContent>
                <DayBars label="Jobs scraped per day" data={s.series.map((d) => ({ label: dayLabel(d.date), scraped: d.scraped }))} bars={[{ key: "scraped", label: "Scraped", color: SERIES[1] }]} />
              </CardContent>
            </Card>
          </div>

          <Card className="mb-6">
            <CardHeader><CardTitle>Last {Math.min(HEATMAP_DAYS, days.length)} days by person</CardTitle><CardDescription>Applied bids per day; darker is more</CardDescription></CardHeader>
            <CardContent>
              {bidders.length === 0 ? <p className="text-sm text-muted-foreground">Nobody has a bidding profile name or bids yet.</p> : (
                <Heatmap days={days.slice(tail)} rows={bidders.map((r) => ({ key: r.employee_id ?? r.name, name: <Name row={r} />, values: r.by_day.slice(tail) }))} />
              )}
            </CardContent>
          </Card>

          <Card className="mb-6 overflow-x-auto">
            <CardHeader><CardTitle>By person</CardTitle><CardDescription>{formatDate(s.date_from)} – {formatDate(s.date_to)}</CardDescription></CardHeader>
            <Table>
              <THead>
                <TR>
                  <TH>Employee</TH>
                  <TH className="text-right">Applied</TH>
                  <TH className="text-right">Per active day</TH>
                  <TH className="text-right">Avg score</TH>
                  <TH className="text-right">Range</TH>
                  <TH>Top resumes</TH>
                  <TH>Last bid</TH>
                  <TH>Trend</TH>
                </TR>
              </THead>
              <TBody>
                {bidders.map((r) => (
                  <TR key={r.employee_id ?? r.name}>
                    <TD>
                      <Name row={r} />
                      {r.employee_id && r.tabs.length > 0 && <div className="text-xs text-muted-foreground">{r.tabs.join(", ")}</div>}
                    </TD>
                    <TD className="tabular text-right font-medium">{r.applied}</TD>
                    <TD className="tabular text-right">{r.days_active ? (r.applied / r.days_active).toFixed(1) : "—"}</TD>
                    <TD className="text-right"><Score value={r.avg_score} /></TD>
                    <TD className="tabular text-right text-muted-foreground">{r.min_score !== null && r.max_score !== null ? `${r.min_score}–${r.max_score}` : "—"}</TD>
                    <TD><ResumeList resumes={r.resumes} /></TD>
                    <TD className="text-muted-foreground">{r.last_date ? formatDate(r.last_date) : "—"}</TD>
                    <TD><Sparkline values={r.by_day} label={`${r.name}: bids per day`} /></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader><CardTitle>Match scores</CardTitle></CardHeader>
              <CardContent><CountBars items={s.score_buckets} color={SERIES[2]} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Job types bid on</CardTitle></CardHeader>
              <CardContent><CountBars items={s.roles} color={SERIES[1]} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Top companies</CardTitle></CardHeader>
              <CardContent><CountBars items={s.companies} color={SERIES[3]} /></CardContent>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
