"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { useCategories } from "@/components/erp/category-select";
import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { PROJECT_STATUS, ProjectDialog, ProjectStatusBadge } from "@/components/projects/project-dialog";
import { ProgressBar } from "@/components/projects/shared";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import { useHireOptions } from "@/lib/queries";
import { useCan, useMe } from "@/lib/session";
import type { Page, Project, ProjectFinancials, TaskProgress } from "@/lib/types";

type MyProjectRow = { project_id: string; received: string; paid: string; net: string; payments: number; base_currency: string };
import { cn, formatDate } from "@/lib/utils";

function ProjectsList() {
  const can = useCan();
  const isHire = useMe().restricted_access;
  const params = useSearchParams();
  const [hire, setHire] = useState(params.get("hire") ?? "");
  const [manager, setManager] = useState("");
  const hires = useHireOptions(useMe().can_select_hire);
  const managers = useQuery({
    queryKey: ["my-managers"],
    queryFn: () => api.get<{ id: string; full_name: string }[]>("/projects/my-managers"),
    enabled: isHire,
  });
  // Whole-project profit only for those who see every project's financials (finance, admin). Everyone else,
  // project managers included, sees what their own payments on each project come to.
  const allFinancials = useMe().permissions["projects.read_financials"] === "all";
  const types = useCategories("project_type", true);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const projects = useQuery({
    queryKey: ["projects", page, q, status, hire, manager],
    queryFn: () =>
      api.get<Page<Project>>("/projects", { page, page_size: 25, q, status, hire_employee_id: hire || undefined, manager_employee_id: manager || undefined }),
    placeholderData: keepPreviousData,
  });
  const ids = projects.data?.items.map((p) => p.id) ?? [];
  const progress = useQuery({
    queryKey: ["task-progress", ids],
    queryFn: async () => {
      const qs = new URLSearchParams(ids.map((id) => ["project_ids", id]));
      return api.get<TaskProgress[]>(`/tasks/progress?${qs}`);
    },
    enabled: ids.length > 0,
  });
  // Profit per project (base currency, cash basis), for those who may see project financials.
  const financials = useQuery({
    queryKey: ["project-profitability", status],
    queryFn: () => api.get<ProjectFinancials[]>("/reports/project-profitability", { status }),
    enabled: allFinancials,
    placeholderData: keepPreviousData,
  });
  const mineOnly = !allFinancials && (can("salary.read") || can("revenue.read"));
  const mine = useQuery({
    queryKey: ["my-project-contribution"],
    queryFn: () => api.get<MyProjectRow[]>("/reports/my-project-contribution"),
    enabled: mineOnly,
    retry: false,
  });
  const columns = useMemo<ColumnDef<Project, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Project",
        cell: ({ row }) => (
          <Link href={`/projects/${row.original.id}`} className="block">
            <span className="block font-medium hover:underline">{row.original.name}</span>
            <span className="block font-mono text-xs text-muted-foreground">{row.original.number}</span>
          </Link>
        ),
      },
      { id: "type", header: "Type", cell: ({ row }) => types.data?.find((t) => t.id === row.original.project_type_category_id)?.name ?? "—" },
      { id: "manager", header: "Manager", cell: ({ row }) => row.original.manager_name ?? "—" },
      ...(isHire ? [] : [{ id: "hire", header: "Hire", cell: ({ row }: { row: { original: Project } }) => row.original.hire_name ?? "—" } satisfies ColumnDef<Project, unknown>]),
      {
        id: "progress",
        header: "Progress",
        enableSorting: false,
        cell: ({ row }) => {
          const p = progress.data?.find((x) => x.project_id === row.original.id);
          const pct = row.original.completion_override ?? p?.percent ?? "0";
          return (
            <div className="w-36">
              <ProgressBar value={pct} />
              <p className="mt-1 text-xs text-muted-foreground">
                {p ? `${p.done}/${p.total} tasks` : "No tasks"}
                {p && p.overdue > 0 && <span className="text-destructive"> · {p.overdue} overdue</span>}
              </p>
            </div>
          );
        },
      },
      ...(isHire
        ? []
        : [
            {
              id: "value",
              header: () => <span className="block text-right">Contract</span>,
              cell: ({ row }: { row: { original: Project } }) => (
                <span className="tabular block text-right">{row.original.contract_value ? `${formatAmount(row.original.contract_value)} ${row.original.currency}` : "—"}</span>
              ),
            } satisfies ColumnDef<Project, unknown>,
          ]),
      ...(allFinancials
        ? [
            {
              id: "profit",
              header: () => (
                <span className="block text-right" title="Revenue received − direct expenses − salary paid (base currency, cash basis)">
                  Profit
                </span>
              ),
              cell: ({ row }: { row: { original: Project } }) => {
                const f = financials.data?.find((x) => x.project_id === row.original.id);
                if (!f) return <span className="block text-right text-muted-foreground">{financials.isLoading ? "…" : "—"}</span>;
                return (
                  <div className="tabular text-right">
                    <span className={cn("font-medium", sign(f.profit_cash) < 0 && "text-destructive")}>
                      {formatAmount(f.profit_cash)} {f.base_currency}
                    </span>
                    <p className="text-xs text-muted-foreground">
                      on {formatAmount(f.revenue)}
                      {f.margin_pct !== null && f.margin_pct !== undefined && ` · ${f.margin_pct}%`}
                    </p>
                  </div>
                );
              },
            } satisfies ColumnDef<Project, unknown>,
          ]
        : mineOnly
          ? [
              {
                id: "mine",
                header: () => (
                  <span className="block text-right" title="Your payment entries on the project: received (your share) − paid to you or for you (salary, expenses tagged to or shared with you)">
                    Your net
                  </span>
                ),
                cell: ({ row }: { row: { original: Project } }) => {
                  const m = mine.data?.find((x) => x.project_id === row.original.id);
                  if (!m) return <span className="block text-right text-muted-foreground">{mine.isLoading ? "…" : "—"}</span>;
                  return (
                    <Link href={`/accounting/payment-entries?project_id=${m.project_id}`} className="tabular block text-right hover:underline" title="Show these payments">
                      <span className={cn("font-medium", sign(m.net) < 0 && "text-destructive")}>
                        {formatAmount(m.net)} {m.base_currency}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {formatAmount(m.received)} in · {formatAmount(m.paid)} out · {m.payments} payment{m.payments === 1 ? "" : "s"}
                      </span>
                    </Link>
                  );
                },
              } satisfies ColumnDef<Project, unknown>,
            ]
          : []),
      { accessorKey: "deadline", header: "Deadline", cell: ({ row }) => formatDate(row.original.deadline) },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <ProjectStatusBadge status={row.original.status} lapsed={row.original.lapsed} />,
      },
    ],
    [types.data, progress.data, financials.data, mine.data, isHire], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <>
      <PageHeader
        title={isHire ? "My projects" : "Projects"}
        description={isHire ? "The projects you've been connected to." : "Customer engagements: team and revenue split, milestones, tasks, timeline and financials."}
        actions={!isHire && (can("projects.manage") || can("projects.create_own")) && <Button onClick={() => setCreating(true)}><Plus /> New project</Button>}
      />
      <Card>
        <div className="flex flex-col gap-2 border-b p-3 sm:flex-row">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search" placeholder="Name or number" className="pl-8" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Status" className="sm:w-40" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {Object.entries(PROJECT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          {!isHire && (hires.data?.length ?? 0) > 0 && (
            <Select aria-label="Hire" className="sm:w-48" value={hire} onChange={(e) => { setHire(e.target.value); setPage(1); }}>
              <option value="">Any hire</option>
              {hires.data?.map((h) => <option key={h.id} value={h.id}>{h.full_name}</option>)}
            </Select>
          )}
          {isHire && (managers.data?.length ?? 0) > 1 && (
            <Select aria-label="Project manager" className="sm:w-48" value={manager} onChange={(e) => { setManager(e.target.value); setPage(1); }}>
              <option value="">Any project manager</option>
              {managers.data?.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
            </Select>
          )}
        </div>
        <DataTable
          columns={columns}
          data={projects.data?.items}
          isLoading={projects.isLoading}
          error={projects.error}
          getRowId={(p) => p.id}
          pagination={projects.data && { page, pageSize: 25, total: projects.data.total, onPageChange: setPage }}
          empty={<EmptyState title="No projects yet" description={isHire ? "A project appears here once you've been connected to it." : undefined} />}
        />
      </Card>
      {creating && <ProjectDialog project={null} onClose={() => setCreating(false)} />}
    </>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectsList />
    </Suspense>
  );
}
