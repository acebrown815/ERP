"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useCategories } from "@/components/erp/category-select";
import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { PROJECT_STATUS, ProjectDialog } from "@/components/projects/project-dialog";
import { ProgressBar } from "@/components/projects/shared";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { useEmployees } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { Page, Project, TaskProgress } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function ProjectsPage() {
  const can = useCan();
  const employees = useEmployees();
  const types = useCategories("project_type", true);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const projects = useQuery({
    queryKey: ["projects", page, q, status],
    queryFn: () => api.get<Page<Project>>("/projects", { page, page_size: 25, q, status }),
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
  const name = (id: string | null | undefined) => employees.data?.find((e) => e.id === id)?.full_name;
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
      { id: "manager", header: "Manager", cell: ({ row }) => name(row.original.manager_employee_id) ?? "—" },
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
      {
        id: "value",
        header: () => <span className="block text-right">Contract</span>,
        cell: ({ row }) => (
          <span className="tabular block text-right">{row.original.contract_value ? `${formatAmount(row.original.contract_value)} ${row.original.currency}` : "—"}</span>
        ),
      },
      { accessorKey: "deadline", header: "Deadline", cell: ({ row }) => formatDate(row.original.deadline) },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge variant={PROJECT_STATUS[row.original.status]?.variant}>{PROJECT_STATUS[row.original.status]?.label}</Badge>,
      },
    ],
    [types.data, employees.data, progress.data], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <>
      <PageHeader
        title="Projects"
        description="Customer engagements: team and revenue split, milestones, tasks, timeline and financials."
        actions={can("projects.manage") && <Button onClick={() => setCreating(true)}><Plus /> New project</Button>}
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
        </div>
        <DataTable
          columns={columns}
          data={projects.data?.items}
          isLoading={projects.isLoading}
          error={projects.error}
          getRowId={(p) => p.id}
          pagination={projects.data && { page, pageSize: 25, total: projects.data.total, onPageChange: setPage }}
          empty={<EmptyState title="No projects yet" />}
        />
      </Card>
      {creating && <ProjectDialog project={null} onClose={() => setCreating(false)} />}
    </>
  );
}
