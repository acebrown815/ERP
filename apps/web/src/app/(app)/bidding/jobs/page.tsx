"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Copy, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { DataBar, JobLink, Score, StatusBadge } from "@/components/bidding/shared";
import { DataTable } from "@/components/erp/data-table";
import { ExportMenu } from "@/components/erp/export-menu";
import { MultiSelect } from "@/components/erp/multi-select";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Checkbox, Input } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { sortParams, type Job, type JobsPage, type JobStatus } from "@/lib/bidding";
import { formatDate } from "@/lib/utils";

const PAGE_SIZE = 50;
type Filters = { q: string; status: string; region: string[]; role: string[]; ats: string[]; skill_level: string[]; from: string; to: string; duplicates: boolean; mine: boolean };
const EMPTY: Filters = { q: "", status: "", region: [], role: [], ats: [], skill_level: [], from: "", to: "", duplicates: false, mine: false };

const asOptions = (values: string[] | undefined) => (values ?? []).map((value) => ({ value, label: value }));

const columns: ColumnDef<Job, unknown>[] = [
  { id: "first_seen", header: "First seen", accessorFn: (j) => j.first_seen ?? "", cell: ({ row }) => <span className="whitespace-nowrap">{formatDate(row.original.first_seen)}</span> },
  {
    id: "job",
    header: "Job",
    accessorFn: (j) => `${j.company} ${j.title}`,
    cell: ({ row }) => {
      const j = row.original;
      return (
        <div className="flex min-w-56 flex-col">
          <JobLink href={j.url} className="font-medium">{j.title}</JobLink>
          <span className="text-xs text-muted-foreground">
            {[j.company, j.location, j.salary, j.is_recruiter ? "recruiter" : ""].filter(Boolean).join(" · ")}
          </span>
        </div>
      );
    },
  },
  { id: "type", header: "Region · role", accessorFn: (j) => `${j.region} ${j.role}`, cell: ({ row }) => <span className="flex flex-col whitespace-nowrap text-xs">{row.original.listings.map((l) => <span key={l}>{l}</span>)}</span> },
  { id: "ats", header: "ATS", accessorFn: (j) => j.ats, cell: ({ row }) => <span className="text-xs">{row.original.ats || "—"}{row.original.skill_level ? ` · ${row.original.skill_level}` : ""}</span> },
  { id: "status", header: "Status", accessorFn: (j) => j.status, cell: ({ row }) => <StatusBadge status={row.original.status} /> },
  {
    id: "bids",
    header: "Bid by",
    enableSorting: false,
    cell: ({ row }) => {
      const j = row.original;
      if (!j.bids.length) return <span className="text-muted-foreground">—</span>;
      return (
        <ul className="flex flex-col gap-0.5 text-xs">
          {/* One tab can hold several bids on the same job, so the tab alone isn't a unique key. */}
          {j.bids.map((b, i) => (
            <li key={`${b.tab}-${i}`} className="flex items-center gap-1.5 whitespace-nowrap">
              <span className="font-medium">{b.employee_name ?? b.tab}</span>
              {b.employee_name && <span className="text-muted-foreground" title="Profile (sheet tab)">({b.tab})</span>}
              <span className="text-muted-foreground">{formatDate(b.date)}</span>
              {b.score !== null && <Score value={b.score} />}
            </li>
          ))}
          {j.duplicate && <li><Badge variant="destructive"><Copy className="size-3" /> Duplicate</Badge></li>}
        </ul>
      );
    },
  },
];

function JobList() {
  const params = useSearchParams();
  const [page, setPage] = useState(1);
  const [f, setF] = useState<Filters>({ ...EMPTY, status: params.get("status") ?? "" });
  const [sorting, setSorting] = useState<SortingState>([]);
  const set = (patch: Partial<Filters>) => {
    setF((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };
  const query = {
    q: f.q || undefined,
    status: f.status || undefined,
    region: f.region,
    role: f.role,
    ats: f.ats,
    skill_level: f.skill_level,
    first_seen_from: f.from || undefined,
    first_seen_to: f.to || undefined,
    duplicates: f.duplicates || undefined,
    mine: f.mine || undefined,
    ...sortParams(sorting),
  };
  const jobs = useQuery({
    queryKey: ["bidding", "jobs", query, page],
    queryFn: () => api.get<JobsPage>("/bidding/jobs", { ...query, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const r = jobs.data;
  const facets = r?.facets;
  const chip = (status: JobStatus | "", label: string, count: number | undefined) => (
    <Button key={status || "all"} variant={f.status === status ? "secondary" : "ghost"} size="sm" onClick={() => set({ status })} aria-pressed={f.status === status}>
      {label}{count !== undefined && <span className="tabular text-muted-foreground">{count}</span>}
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Job list"
        description="Every job the scraper found, and who bid on it. Bids are matched by link, then by company and title."
        actions={<ExportMenu path="/bidding/jobs/export" params={{ q: query.q, status: query.status, region: f.region, role: f.role, ats: f.ats, skill_level: f.skill_level, first_seen_from: query.first_seen_from, first_seen_to: query.first_seen_to, duplicates: f.duplicates ? "true" : undefined, mine: f.mine ? "true" : undefined, sort: query.sort, desc: query.desc ? "true" : undefined }} />}
      />
      <DataBar data={r?.data} />
      <Card>
        <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2">
          {chip("", "All", r ? r.not_bid + r.applied : undefined)}
          {chip("not_bid", "Not bid", r?.not_bid)}
          {chip("applied", "Applied", r?.applied)}
        </div>
        <div className="flex flex-wrap items-end gap-2 border-b p-3">
          <div className="relative min-w-48 flex-1">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search jobs" placeholder="Title, company, location…" className="pl-8" value={f.q} onChange={(e) => set({ q: e.target.value })} />
          </div>
          <div className="w-32"><MultiSelect placeholder="Region" noun="regions" options={asOptions(facets?.regions)} value={f.region} onChange={(region) => set({ region })} /></div>
          <div className="w-36"><MultiSelect placeholder="Role" noun="roles" options={asOptions(facets?.roles)} value={f.role} onChange={(role) => set({ role })} /></div>
          <div className="w-36"><MultiSelect placeholder="ATS" noun="ATS" options={asOptions(facets?.ats)} value={f.ats} onChange={(ats) => set({ ats })} /></div>
          <div className="w-32"><MultiSelect placeholder="Level" noun="levels" options={asOptions(facets?.skill_levels)} value={f.skill_level} onChange={(skill_level) => set({ skill_level })} /></div>
          <Input aria-label="First seen from" type="date" className="w-40" value={f.from} onChange={(e) => set({ from: e.target.value })} />
          <Input aria-label="First seen to" type="date" className="w-40" value={f.to} onChange={(e) => set({ to: e.target.value })} />
          <label className="flex h-9 items-center gap-1.5 text-sm"><Checkbox checked={f.duplicates} onChange={(e) => set({ duplicates: e.target.checked })} /> Duplicates</label>
          <label className="flex h-9 items-center gap-1.5 text-sm"><Checkbox checked={f.mine} onChange={(e) => set({ mine: e.target.checked })} /> Mine</label>
          {JSON.stringify({ ...f, status: "" }) !== JSON.stringify({ ...EMPTY }) && (
            <Button variant="ghost" size="sm" onClick={() => set({ ...EMPTY, status: f.status })}>Clear</Button>
          )}
        </div>
        <DataTable
          columns={columns}
          data={r?.items}
          isLoading={jobs.isLoading}
          error={jobs.error}
          onRetry={() => jobs.refetch()}
          getRowId={(j) => j.key}
          pagination={r && { page, pageSize: PAGE_SIZE, total: r.total, onPageChange: setPage }}
          sort={{
            value: sorting,
            onChange: (next) => {
              setSorting(next);
              setPage(1);
            },
          }}
          empty={
            <EmptyState
              title="No jobs match"
              description={r?.data.jobs.configured === false ? "The job-list sheet is not connected yet." : f.mine ? "Mine shows jobs bid on from your own profiles. Untick it to see everyone's." : "Try fewer filters."}
              action={f.mine ? <Button variant="outline" asChild><Link href="/bidding/me">Check my profile name</Link></Button> : undefined}
            />
          }
        />
      </Card>
    </>
  );
}

export default function JobListPage() {
  return (
    <Suspense>
      <JobList />
    </Suspense>
  );
}
