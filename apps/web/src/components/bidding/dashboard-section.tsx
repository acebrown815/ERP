"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CountBars, DataBar, DayBars, dayLabel, pct, ResumeList, Score } from "@/components/bidding/shared";
import { SERIES, Sparkline, StatTile } from "@/components/charts/charts";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import { lastDays, useProfile, useSeesAllBids, useStats, type EmployeeRow, type Stats } from "@/lib/bidding";
import { dashboardScope } from "@/lib/dashboard-scope";

const DAYS = 30;
const PEOPLE_SHOWN = 10;

function ByPerson({ rows }: { rows: EmployeeRow[] }) {
  const hidden = rows.length - PEOPLE_SHOWN;
  return (
    <Card className="overflow-x-auto">
      <CardHeader><CardTitle>By person</CardTitle><CardDescription>Most bids first, last {DAYS} days</CardDescription></CardHeader>
      {rows.length === 0 ? <CardContent><p className="text-sm text-muted-foreground">Nobody has a bidding profile name or bids yet.</p></CardContent> : (
        <Table>
          <THead>
            <TR>
              <TH>Employee</TH>
              <TH className="text-right">Today</TH>
              <TH className="text-right">Last {DAYS} days</TH>
              <TH className="text-right">Avg score</TH>
              <TH>Top resumes</TH>
            </TR>
          </THead>
          <TBody>
            {rows.slice(0, PEOPLE_SHOWN).map((r) => (
              <TR key={r.employee_id ?? r.name}>
                <TD>
                  {r.employee_id
                    ? <Link href={`/bidding/employee?id=${r.employee_id}`} className="font-medium hover:underline">{r.name}</Link>
                    : <span className="text-muted-foreground" title="A sheet tab nobody has claimed as their bidding profile name">{r.name} <span className="text-xs">(unclaimed tab)</span></span>}
                </TD>
                <TD className="tabular text-right">{r.by_day.at(-1) || "—"}</TD>
                <TD className="tabular text-right font-medium">{r.applied}</TD>
                <TD className="text-right"><Score value={r.avg_score} /></TD>
                <TD><ResumeList resumes={r.resumes} /></TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {hidden > 0 && <p className="border-t px-4 py-2 text-xs text-muted-foreground">{hidden} more on <Link href="/bidding" className="underline">Team Overview</Link></p>}
    </Card>
  );
}

function useDashboardStats() {
  const [range] = useState(() => lastDays(DAYS));
  const seesAll = useSeesAllBids();
  const profile = useProfile(); // a 404 just means no employee record
  const { team, employeeId } = dashboardScope(profile.data, seesAll);
  // Wait for the profile, so a bidder with a manager role never gets the team's numbers first.
  return { stats: useStats(range, employeeId, null, !profile.isPending), team };
}

/**
 * The headline numbers, as tiles for the dashboard's top grid. Blank while they can't be shown:
 * BiddingDashboardSection explains why (not linked, no profile names, or an error).
 */
export function BiddingTiles() {
  const { stats, team } = useDashboardStats();
  const s = stats.data;
  if (stats.isError || s?.profile_missing) return null;
  return (
    <>
      <StatTile label={team ? "Bids today" : "My bids today"} value={s ? (s.series.at(-1)?.applied ?? 0) : undefined} hint={s && `Yesterday: ${s.series.at(-2)?.applied ?? 0}`} />
      <StatTile
        label={team ? `Bids, last ${DAYS} days` : `My bids, last ${DAYS} days`}
        value={s?.applied}
        hint={s && team ? `${s.active_bidders} people bidding` : undefined}
        spark={s && <Sparkline values={s.series.map((d) => d.applied)} label="Bids per day" />}
      />
      <StatTile label={team ? "Average match score" : "My average match score"} value={s ? (s.avg_score ?? "—") : undefined} hint={`Last ${DAYS} days`} />
      {team ? (
        <StatTile label="Job list covered" value={s && pct(s.coverage_pct)} hint={s && `${s.scraped_bid} of ${s.scraped} scraped jobs, last ${DAYS} days`} />
      ) : (
        <StatTile label="My bids from the job list" value={s && s.applied - s.outside_job_list} hint={s && `${s.outside_job_list} found elsewhere, last ${DAYS} days`} />
      )}
    </>
  );
}

function Details({ s, all }: { s: Stats; all: boolean }) {
  const chart = (
    <Card>
      <CardHeader><CardTitle>Bids per day</CardTitle><CardDescription>{all ? "Applied bids, whole team" : "Your applied bids"}, last {DAYS} days</CardDescription></CardHeader>
      <CardContent>
        <DayBars label="Bids per day" height={200} data={s.series.map((d) => ({ label: dayLabel(d.date), applied: d.applied }))} bars={[{ key: "applied", label: "Applied", color: SERIES[0] }]} />
      </CardContent>
    </Card>
  );
  return (
    <>
      <DataBar data={s.data} />
      {all ? (
        <div className="flex flex-col gap-4">
          {chart}
          <ByPerson rows={s.employees} />
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {chart}
          <Card>
            <CardHeader><CardTitle>Bids by profile</CardTitle><CardDescription>Last {DAYS} days</CardDescription></CardHeader>
            <CardContent><CountBars items={s.profiles} empty="No bids in the last 30 days." /></CardContent>
          </Card>
        </div>
      )}
    </>
  );
}

/**
 * The dashboard's bidding chart and breakdown: the signed-in person's own numbers if they bid, or the team's for a
 * manager who doesn't (dashboardScope). The API still enforces who may see what. It loads on its own, so a slow sheet
 * read never holds up the rest of the dashboard.
 */
export function BiddingDashboardSection() {
  const { stats, team } = useDashboardStats();
  const s = stats.data;
  const unlinked = stats.error instanceof ApiError && stats.error.status === 404;

  let body;
  if (unlinked) {
    body = (
      <Card><CardContent className="py-4 text-sm text-muted-foreground">
        Your sign-in isn&apos;t linked to an employee record yet, so there are no bidding numbers to show. Ask an administrator to link it.
      </CardContent></Card>
    );
  } else if (stats.isError) {
    body = <ErrorState error={stats.error} onRetry={() => stats.refetch()} />;
  } else if (!s) {
    body = <TableSkeleton rows={4} />;
  } else if (s.profile_missing) {
    body = (
      <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm text-muted-foreground">
        Add your bidding profile names to see your numbers here.
        <Button size="sm" asChild><Link href="/bidding/me">Add profile names</Link></Button>
      </CardContent></Card>
    );
  } else {
    body = <Details s={s} all={team} />;
  }

  return (
    <section aria-labelledby="dashboard_bidding" className="mb-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="dashboard_bidding" className="text-base font-semibold">{team ? "Team bidding" : "My bidding"}</h2>
        <Button variant="ghost" size="sm" asChild>
          <Link href={team ? "/bidding" : "/bidding/me"}>{team ? "Team overview" : "My bidding"} <ArrowRight /></Link>
        </Button>
      </div>
      {body}
    </section>
  );
}
