"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Copy, ExternalLink, RefreshCw, Search, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { Legend, SERIES } from "@/components/charts/charts";
import { DataTable } from "@/components/erp/data-table";
import { ExportMenu } from "@/components/erp/export-menu";
import { EmptyState } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/input";
import { Badge, Label } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { lastDays, sortParams, useRefreshSheets, type Bid, type BidsPage, type Count, type DataState, type JobStatus, type Range } from "@/lib/bidding";
import { cn, formatDate, formatDateTime } from "@/lib/utils";

// ---- data freshness --------------------------------------------------------------------------------------

/** "Data as of 10:42 · Refresh", plus any sheet that is not set up or failed to load. */
export function DataBar({ data, className }: { data: DataState | undefined; className?: string }) {
  const refresh = useRefreshSheets();
  if (!data) return null;
  const problems: string[] = [];
  if (!data.bids.configured) problems.push("The bids sheet is not connected yet (Settings → Bidding Sheets).");
  else if (data.bids.error) problems.push(`Bids sheet: ${data.bids.error}`);
  if (!data.jobs.configured) problems.push("The job-list sheet is not connected yet (Settings → Bidding Sheets).");
  else if (data.jobs.error) problems.push(`Job-list sheet: ${data.jobs.error}`);
  return (
    <div className={cn("mb-4 flex flex-col gap-2", className)}>
      {problems.length > 0 && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div className="flex flex-col gap-0.5">
            {problems.map((p) => <span key={p}>{p}</span>)}
            {(data.bids.error || data.jobs.error) && <span className="text-xs text-muted-foreground">Showing the last data that loaded.</span>}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>Data as of {formatDateTime(data.built_at)}</span>
        {data.job_list_from && <span>· Job list goes back to {formatDate(data.job_list_from)}</span>}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          loading={refresh.isPending}
          onClick={() => refresh.mutate(undefined, { onError: () => toast.error("Could not refresh the sheets") })}
        >
          {!refresh.isPending && <RefreshCw />} Refresh
        </Button>
      </div>
    </div>
  );
}

// ---- small pieces ----------------------------------------------------------------------------------------

const STATUS: Record<JobStatus, { label: string; variant: "success" | "muted" }> = {
  applied: { label: "Applied", variant: "success" },
  not_bid: { label: "Not bid", variant: "muted" },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const s = STATUS[status];
  return <Badge variant={s.variant}>{s.label}</Badge>;
}

export function Score({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  return (
    <span className={cn("tabular", value >= 80 ? "text-success" : value < 60 ? "text-destructive" : undefined)}>
      {Number.isInteger(value) ? value : value.toFixed(1)}
    </span>
  );
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

/** "2026-11-03" → "Nov 3" for chart axes. */
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(y!, (m ?? 1) - 1, d ?? 1)));
}

export function JobLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cn("inline-flex items-center gap-1 hover:underline", className)}>
      {children}
      <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden />
    </a>
  );
}

// ---- date range ------------------------------------------------------------------------------------------

const PRESETS = [1, 7, 14, 30, 90];

export function RangePicker({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const preset = PRESETS.find((n) => {
    const r = lastDays(n);
    return r.from === value.from && r.to === value.to;
  });
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex flex-col gap-1">
        <Label htmlFor="range_preset">Period</Label>
        <Select id="range_preset" className="w-36" value={preset ?? ""} onChange={(e) => e.target.value && onChange(lastDays(Number(e.target.value)))}>
          {PRESETS.map((n) => <option key={n} value={n}>{n === 1 ? "Today" : `Last ${n} days`}</option>)}
          {!preset && <option value="">Custom</option>}
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="range_from">From</Label>
        <Input id="range_from" type="date" className="w-40" value={value.from} max={value.to} onChange={(e) => e.target.value && onChange({ ...value, from: e.target.value })} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="range_to">To</Label>
        <Input id="range_to" type="date" className="w-40" value={value.to} min={value.from} onChange={(e) => e.target.value && onChange({ ...value, to: e.target.value })} />
      </div>
    </div>
  );
}

// ---- charts ----------------------------------------------------------------------------------------------

const axis = { stroke: "var(--chart-axis)", fontSize: 11, tickLine: false } as const;

type Point = Record<string, string | number | null>;

/** Whole-number bars per day (bids, scraped jobs). */
export function DayBars({ data, bars, label, height = 240 }: { data: Point[]; bars: { key: string; label: string; color: string }[]; label: string; height?: number }) {
  return (
    <figure className="flex flex-col gap-2" aria-label={label}>
      {bars.length > 1 && <Legend series={bars} />}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="20%">
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="label" {...axis} axisLine={{ stroke: "var(--chart-grid)" }} interval="preserveStartEnd" minTickGap={12} />
            <YAxis {...axis} axisLine={false} width={36} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: "var(--muted)", opacity: 0.6 }}
              contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: "var(--foreground)", fontWeight: 500 }}
            />
            {bars.map((b) => <Bar key={b.key} dataKey={b.key} name={b.label} fill={b.color} radius={[3, 3, 0, 0]} maxBarSize={24} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/** Ranked list with inline bars: score bands, resumes, roles, companies. */
export function CountBars({ items, empty = "Nothing yet", color = SERIES[0] }: { items: Count[]; empty?: string; color?: string }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  if (!items.some((i) => i.count > 0)) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="flex flex-col gap-1.5 text-sm">
      {items.map((i) => (
        <li key={i.name} className="grid grid-cols-[minmax(6rem,10rem)_1fr_2.5rem] items-center gap-2">
          <span className="truncate" title={i.name}>{i.name}</span>
          <span className="h-2 rounded-full bg-muted" aria-hidden>
            <span className="block h-2 rounded-full" style={{ width: `${(100 * i.count) / max}%`, background: color }} />
          </span>
          <span className="tabular text-right text-muted-foreground">{i.count}</span>
        </li>
      ))}
    </ul>
  );
}

const TOP_RESUMES = 3;

/** The most used resumes with their counts. Long names are cut short; the rest is "+N more", listed on hover. */
export function ResumeList({ resumes }: { resumes: Count[] }) {
  if (!resumes.length) return <span className="text-muted-foreground">—</span>;
  const others = resumes.slice(TOP_RESUMES);
  return (
    <ul className="flex flex-col gap-0.5 text-xs">
      {resumes.slice(0, TOP_RESUMES).map((r) => (
        <li key={r.name} className="flex max-w-64 items-baseline gap-1" title={r.name}>
          <span className="truncate">{r.name}</span>
          <span className="tabular shrink-0 text-muted-foreground">{r.count}</span>
        </li>
      ))}
      {others.length > 0 && (
        <li className="text-muted-foreground" title={others.map((r) => `${r.name} (${r.count})`).join("\n")}>+{others.length} more</li>
      )}
    </ul>
  );
}

/** Employees × days, darker = more bids. */
export function Heatmap({ days, rows }: { days: string[]; rows: { key: string; name: ReactNode; values: number[] }[] }) {
  const max = Math.max(1, ...rows.flatMap((r) => r.values));
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-card pr-3 text-left font-medium text-muted-foreground" />
            {days.map((d) => <th key={d} className="px-0.5 pb-1 font-normal text-muted-foreground" title={formatDate(d)}>{dayLabel(d).split(" ")[1]}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="sticky left-0 max-w-44 truncate bg-card py-0.5 pr-3">{r.name}</td>
              {r.values.map((v, i) => (
                <td key={days[i]} className="px-0.5 py-0.5">
                  <span
                    className="flex size-6 items-center justify-center rounded-sm tabular"
                    style={{ background: v ? `color-mix(in oklch, var(--chart-1) ${20 + (80 * v) / max}%, transparent)` : "var(--muted)", color: v / max > 0.55 ? "white" : undefined }}
                    title={`${formatDate(days[i])}: ${v} bid${v === 1 ? "" : "s"}`}
                  >
                    {v || ""}
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- bids table ------------------------------------------------------------------------------------------

const PAGE_SIZE = 25;

type BidFilters = { q: string; from: string; to: string; min_score: string; duplicates: boolean; outside: boolean };

/** Filterable, paginated bids. `employeeId` / `tab` pin it to one person or sheet tab. */
export function BidsTable({ employeeId, tab, showEmployee = true, initialRange }: { employeeId?: string | null; tab?: string | null; showEmployee?: boolean; initialRange?: Range }) {
  const [page, setPage] = useState(1);
  const [f, setF] = useState<BidFilters>({ q: "", from: initialRange?.from ?? "", to: initialRange?.to ?? "", min_score: "", duplicates: false, outside: false });
  const [sorting, setSorting] = useState<SortingState>([]);
  const set = (patch: Partial<BidFilters>) => {
    setF((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };
  const query = {
    employee_id: employeeId ?? undefined,
    tab: tab ?? undefined,
    q: f.q || undefined,
    date_from: f.from || undefined,
    date_to: f.to || undefined,
    min_score: f.min_score || undefined,
    duplicates: f.duplicates || undefined,
    outside: f.outside || undefined,
    ...sortParams(sorting),
  };
  const bids = useQuery({
    queryKey: ["bidding", "bids", query, page],
    queryFn: () => api.get<BidsPage>("/bidding/bids", { ...query, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const allColumns: ColumnDef<Bid, unknown>[] = [
    { id: "date", header: "Date", accessorFn: (b) => b.date ?? "", cell: ({ row }) => (row.original.date ? formatDate(row.original.date) : <span className="text-muted-foreground">—</span>) },
    {
      id: "employee",
      header: "Employee",
      accessorFn: (b) => b.employee_name ?? b.tab,
      cell: ({ row }) =>
        row.original.employee_id ? (
          <Link href={`/bidding/employee?id=${row.original.employee_id}`} className="hover:underline">{row.original.employee_name}</Link>
        ) : (
          <span className="text-muted-foreground" title="Sheet tab nobody has claimed">{row.original.tab}</span>
        ),
    },
    { id: "profile", header: "Profile", accessorFn: (b) => b.tab, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{row.original.tab}</span> },
    {
      id: "job",
      header: "Job",
      accessorFn: (b) => `${b.company} ${b.title}`,
      cell: ({ row }) => {
        const b = row.original;
        return (
          <div className="flex min-w-48 flex-col">
            <JobLink href={b.link} className="font-medium">{b.title || b.link}</JobLink>
            <span className="text-xs text-muted-foreground">{[b.company, b.location, b.salary].filter(Boolean).join(" · ")}</span>
          </div>
        );
      },
    },
    { id: "score", header: "Score", accessorFn: (b) => b.score ?? -1, cell: ({ row }) => <Score value={row.original.score} /> },
    { id: "resume", header: "Resume", accessorFn: (b) => b.resume, cell: ({ row }) => row.original.resume || <span className="text-muted-foreground">—</span> },
    {
      id: "list",
      header: "Job list",
      accessorFn: (b) => `${b.region ?? ""} ${b.role ?? ""}`,
      cell: ({ row }) => {
        const b = row.original;
        return (
          <div className="flex flex-wrap items-center gap-1">
            {b.in_job_list ? <span className="text-xs">{b.listings.join(", ")}</span> : <span className="text-xs text-muted-foreground">Not in list</span>}
            {b.duplicate && <Badge variant="destructive" title="This job was also bid on from another profile"><Copy className="size-3" /> Duplicate</Badge>}
          </div>
        );
      },
    },
  ];
  const columns = allColumns.filter((c) => showEmployee || c.id !== "employee");

  return (
    <div>
      <div className="flex flex-wrap items-end gap-2 border-b p-3">
        <div className="relative min-w-48 flex-1">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input aria-label="Search bids" placeholder="Title, company, link…" className="pl-8" value={f.q} onChange={(e) => set({ q: e.target.value })} />
        </div>
        <Input aria-label="From" type="date" className="w-40" value={f.from} onChange={(e) => set({ from: e.target.value })} />
        <Input aria-label="To" type="date" className="w-40" value={f.to} onChange={(e) => set({ to: e.target.value })} />
        <Select aria-label="Minimum score" className="w-32" value={f.min_score} onChange={(e) => set({ min_score: e.target.value })}>
          <option value="">Any score</option>
          <option value="90">90+</option>
          <option value="80">80+</option>
          <option value="70">70+</option>
        </Select>
        <label className="flex h-9 items-center gap-1.5 text-sm"><Checkbox checked={f.duplicates} onChange={(e) => set({ duplicates: e.target.checked })} /> Duplicates</label>
        <label className="flex h-9 items-center gap-1.5 text-sm"><Checkbox checked={f.outside} onChange={(e) => set({ outside: e.target.checked })} /> Not in job list</label>
        <ExportMenu path="/bidding/bids/export" params={Object.fromEntries(Object.entries(query).map(([k, v]) => [k, v === undefined ? undefined : String(v)]))} />
      </div>
      <DataTable
        columns={columns}
        data={bids.data?.items}
        isLoading={bids.isLoading}
        error={bids.error}
        onRetry={() => bids.refetch()}
        getRowId={(b) => `${b.tab}:${b.row}`}
        pagination={bids.data && { page, pageSize: PAGE_SIZE, total: bids.data.total, onPageChange: setPage }}
        sort={{
          value: sorting,
          onChange: (next) => {
            setSorting(next);
            setPage(1);
          },
        }}
        empty={<EmptyState title="No bids match" description="Bids appear here once the extension writes them to the sheet." />}
      />
    </div>
  );
}
