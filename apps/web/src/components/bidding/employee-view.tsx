"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Plus, X } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { BidsTable, CountBars, DataBar, DayBars, dayLabel, pct, RangePicker } from "@/components/bidding/shared";
import { SERIES, StatTile } from "@/components/charts/charts";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Label } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { lastDays, useStats, type Profile, type Range } from "@/lib/bidding";
import { cn } from "@/lib/utils";

const sameName = (a: string, b: string) => a.trim().replace(/\s+/g, " ").toLowerCase() === b.trim().replace(/\s+/g, " ").toLowerCase();

/**
 * One person's bidding numbers. `employeeId` is required: with none, the API answers with the whole company for
 * anyone who can see everyone's bids. `onSetProfile` marks it as the signed-in user's own page. `leading` goes at the
 * left of the top row, across from the period and profile pickers.
 */
export function EmployeeBidding({ employeeId, onSetProfile, leading }: { employeeId: string; onSetProfile?: () => void; leading?: ReactNode }) {
  const [range, setRange] = useState<Range>(() => lastDays(30));
  const [profile, setProfile] = useState("");
  const stats = useStats(range, employeeId, profile || null);
  const s = stats.data;
  const several = (s?.profile_names.length ?? 0) > 1;
  const noResume = s ? s.applied - s.resumes.reduce((n, r) => n + r.count, 0) : 0;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {leading}
          <DataBar data={s?.data} className="mb-0" />
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {several && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="bid_profile">Profile</Label>
              <Select id="bid_profile" className="w-44" value={profile} onChange={(e) => setProfile(e.target.value)}>
                <option value="">All profiles</option>
                {s?.profile_names.map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
            </div>
          )}
          <RangePicker value={range} onChange={setRange} />
        </div>
      </div>
      {stats.isError ? <ErrorState error={stats.error} onRetry={() => stats.refetch()} /> : !s ? <TableSkeleton /> : (
        <>
          {s.profile_missing && (
            <div className="mb-4 flex flex-wrap items-center gap-3 rounded-md border bg-muted/40 px-4 py-3 text-sm">
              <CircleAlert className="size-4 text-warning" aria-hidden />
              <span className="flex-1">
                {onSetProfile
                  ? "Set your bidding profile name so the ERP can find your tab in the bids sheet."
                  : `${s.employee_name ?? "This employee"} has no bidding profile name yet, so none of the sheet tabs is linked to them.`}
              </span>
              {onSetProfile ? (
                <Button size="sm" onClick={onSetProfile}>Set profile name</Button>
              ) : (
                <Button size="sm" variant="outline" asChild><Link href="/settings/bidding">Bidding sheets</Link></Button>
              )}
            </div>
          )}
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <StatTile label="Applied" value={s.applied} hint={`${s.series.filter((d) => d.applied > 0).length} active days of ${s.series.length}`} />
            <StatTile label="Average match score" value={s.avg_score ?? "—"} hint="Score from the extension's analysis" />
            <StatTile
              label="From the job list"
              value={s.scraped_bid}
              hint={`of ${s.scraped} scraped in this period${s.outside_job_list ? ` · ${s.outside_job_list} bids found elsewhere` : ""}`}
            />
          </div>
          <Card className="mb-6">
            <CardHeader><CardTitle>Bids per day</CardTitle><CardDescription>Applied bids, by the Date column in the sheet</CardDescription></CardHeader>
            <CardContent>
              <DayBars label="Bids per day" data={s.series.map((d) => ({ label: dayLabel(d.date), applied: d.applied }))} bars={[{ key: "applied", label: "Applied", color: SERIES[0] }]} />
            </CardContent>
          </Card>
          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            {several && !profile && (
              <Card className="lg:col-span-2">
                <CardHeader><CardTitle>Bids by profile</CardTitle><CardDescription>Applied bids in this period, per sheet tab</CardDescription></CardHeader>
                <CardContent><CountBars items={s.profiles} empty="No bids in this period" /></CardContent>
              </Card>
            )}
            <Card>
              <CardHeader><CardTitle>Match scores</CardTitle></CardHeader>
              <CardContent><CountBars items={s.score_buckets} color={SERIES[2]} /></CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Resumes used</CardTitle>
                <CardDescription>
                  {s.resumes.length} resume{s.resumes.length === 1 ? "" : "s"}, most used first
                  {noResume > 0 && ` · ${noResume} bid${noResume === 1 ? "" : "s"} with no resume recorded`}
                </CardDescription>
              </CardHeader>
              <CardContent className="max-h-96 overflow-y-auto"><CountBars items={s.resumes} empty="No resume recorded" /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Job types</CardTitle><CardDescription>Region and role of the job-list tab each bid matched</CardDescription></CardHeader>
              <CardContent><CountBars items={s.roles} color={SERIES[1]} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Top 10 companies</CardTitle></CardHeader>
              <CardContent><CountBars items={s.companies} color={SERIES[3]} /></CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader><CardTitle>Bids</CardTitle><CardDescription>Coverage of the job list in this period: {pct(s.coverage_pct)}</CardDescription></CardHeader>
            {/* Starts on the page's period; a new period or profile starts it again. */}
            <BidsTable key={`${profile}|${range.from}|${range.to}`} employeeId={employeeId} tab={profile || null} showEmployee={false} initialRange={range} />
          </Card>
        </>
      )}
    </>
  );
}

/**
 * The employee's bidding profile names as removable chips, with a box to add one: each is a tab in the bids sheet
 * (the extension's Sheet Tab Name). Every add or remove saves the whole list straight away.
 */
export function ProfileNamesEditor({
  employeeId,
  employeeName,
  names,
  available,
  missing = [],
  path,
  compact = false,
  onSaved,
}: {
  employeeId: string;
  employeeName?: string;
  names: string[];
  /** Tab names to suggest; ones already on the list are left out. */
  available: string[];
  /** Names with no tab in the sheet yet. */
  missing?: string[];
  path: string;
  compact?: boolean;
  onSaved?: () => void;
}) {
  const qc = useQueryClient();
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string>();
  const save = useMutation({
    mutationFn: (next: string[]) => api.put<Profile>(path, { profile_names: next }),
    onSuccess: () => {
      setError(undefined);
      setTyped("");
      qc.invalidateQueries({ queryKey: ["bidding"] });
      qc.invalidateQueries({ queryKey: ["employee", employeeId] });
      onSaved?.();
    },
    onError: (err) => setError(err instanceof ApiError ? err.fieldErrors().bidding_profile_names ?? err.message : "Could not save"),
  });

  const inList = (name: string) => names.some((n) => sameName(n, name));
  const add = () => {
    const name = typed.trim().replace(/\s+/g, " ");
    if (!name) return;
    if (inList(name)) {
      setTyped("");
      return;
    }
    save.mutate([...names, name]);
  };
  const who = employeeName ? ` for ${employeeName}` : "";
  const listId = `tabs-${employeeId}`;

  return (
    <div className="flex flex-col gap-2">
      {names.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Bidding profile names${who}`}>
          {names.map((n) => {
            const noTab = missing.some((m) => sameName(m, n));
            return (
              <li key={n}>
                <span
                  className={cn("inline-flex items-center gap-1 rounded-md border py-0.5 pl-2 pr-1 text-xs", noTab ? "border-warning/50 text-muted-foreground" : "bg-muted/50")}
                  title={noTab ? "No tab with this name yet; it appears on the first Mark as Applied" : undefined}
                >
                  {n}
                  {noTab && <span className="text-warning">· no tab yet</span>}
                  <button
                    type="button"
                    aria-label={`Remove ${n}${who}`}
                    disabled={save.isPending}
                    className="rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                    onClick={() => save.mutate(names.filter((x) => x !== n))}
                  >
                    <X className="size-3" aria-hidden />
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <Input
          aria-label={`Add a bidding profile name${who}`}
          aria-invalid={!!error}
          list={listId}
          className={compact ? "h-8 w-48" : "w-64"}
          value={typed}
          maxLength={100}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={names.length ? "Add another" : "Add a profile name"}
        />
        <datalist id={listId}>{available.filter((t) => !inList(t)).map((t) => <option key={t} value={t} />)}</datalist>
        <Button type="submit" variant="outline" size="sm" loading={save.isPending} disabled={!typed.trim()}><Plus /> Add</Button>
      </form>
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/** My Bidding → Profile: the names, and what the sheet has for each. */
export function ProfileForm({ profile, path, onSaved }: { profile: Profile; path: string; onSaved?: () => void }) {
  const left = profile.available_tabs.filter((t) => !profile.profile_names.some((n) => sameName(n, t)));
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Add one name for each Sheet Tab Name you use in the extension (Profile → Settings → Google Sheets Sync). Capital letters and extra spaces don&apos;t matter.
      </p>
      <ProfileNamesEditor
        employeeId={profile.employee_id}
        names={profile.profile_names}
        available={profile.available_tabs}
        missing={profile.tabs.filter((t) => !t.found).map((t) => t.name)}
        path={path}
        onSaved={onSaved}
      />
      {profile.tabs.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {profile.tabs.map((t) => (
            <li key={t.name} className="flex items-center gap-2">
              {t.found ? (
                <>
                  <CircleCheck className="size-4 text-success" aria-hidden />
                  Tab “{t.name}” found: {t.applied} applied.
                </>
              ) : (
                <>
                  <CircleAlert className="size-4 text-warning" aria-hidden />
                  No tab named “{t.name}” in the bids sheet yet. It is created on the first Mark as Applied.
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {left.length > 0 && <p className="text-xs text-muted-foreground">Tabs you can pick: {left.join(", ")}</p>}
    </div>
  );
}
