"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { CategorySelect, useCategories } from "@/components/erp/category-select";
import { DataTable } from "@/components/erp/data-table";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { EmployeePicker, PartyPicker } from "@/components/erp/pickers";
import { EmptyState } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { formatAmount, sum } from "@/lib/money";
import { useCurrencies, useEmployees } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { Page, Project } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const STATUS: Record<string, { label: string; variant: "success" | "warning" | "muted" | "default" }> = {
  planned: { label: "Planned", variant: "default" },
  active: { label: "Active", variant: "success" },
  on_hold: { label: "On hold", variant: "warning" },
  completed: { label: "Completed", variant: "muted" },
  cancelled: { label: "Cancelled", variant: "muted" },
};

type MemberDraft = { employee_id: string | null; role: string; pct: string };

function ProjectDialog({ project, onClose }: { project: Project | null; onClose: () => void }) {
  const qc = useQueryClient();
  const currencies = useCurrencies();
  const [form, setForm] = useState({
    name: project?.name ?? "",
    customer_party_id: project?.customer_party_id ?? null,
    manager_employee_id: project?.manager_employee_id ?? null,
    ptype: { category_id: project?.project_type_category_id ?? null, other_text: project?.project_type_other_text ?? "" },
    start_date: project?.start_date ?? "",
    deadline: project?.deadline ?? "",
    contract_value: project?.contract_value ? project.contract_value.replace(/\.?0+$/, "") : "",
    currency: project?.currency ?? "",
    status: project?.status ?? "active",
    description: project?.description ?? "",
  });
  const [members, setMembers] = useState<MemberDraft[]>(
    (project?.members ?? []).map((m) => ({ employee_id: m.employee_id, role: m.role ?? "", pct: m.default_allocation_pct?.replace(/\.?0+$/, "") ?? "" })),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const pctTotal = sum(members.map((m) => m.pct));

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name, customer_party_id: form.customer_party_id, manager_employee_id: form.manager_employee_id,
        project_type_category_id: form.ptype.category_id, project_type_other_text: form.ptype.other_text || null,
        start_date: form.start_date || null, deadline: form.deadline || null, contract_value: form.contract_value || null,
        currency: form.currency || null, status: form.status, description: form.description || null,
      };
      const saved = project ? await api.patch<Project>(`/projects/${project.id}`, { ...body, version: project.version }) : await api.post<Project>("/projects", body);
      return api.put<Project>(`/projects/${saved.id}/members`, {
        members: members.filter((m) => m.employee_id).map((m) => ({ employee_id: m.employee_id, role: m.role || null, default_allocation_pct: m.pct || null })),
      });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success(project ? "Project saved" : `${p.name} created (${p.number})`);
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        toast.error(err.message);
      }
    },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{project ? `Edit ${project.name}` : "New project"}</DialogTitle>
          <DialogDescription>Tasks, milestones and the timeline arrive in Phase 4. For now a project links payments and pre-fills the revenue split.</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <FormField id="pr_name" label="Name" required error={errors.name} className="sm:col-span-2"><Input id="pr_name" value={form.name} onChange={(e) => set("name", e.target.value)} /></FormField>
          <FormField id="pr_customer" label="Customer" error={errors.customer_party_id}>
            <PartyPicker id="pr_customer" kinds={["customer", "other"]} value={form.customer_party_id} onChange={(v) => set("customer_party_id", v)} />
          </FormField>
          <FormField id="pr_manager" label="Project manager" error={errors.manager_employee_id}>
            <EmployeePicker id="pr_manager" value={form.manager_employee_id} onChange={(v) => set("manager_employee_id", v)} />
          </FormField>
          <CategorySelect group="project_type" label="Project type" required value={form.ptype} onChange={(v) => set("ptype", v)}
            error={errors.project_type_category_id ?? errors.project_type_other_text} />
          <FormField id="pr_status" label="Status">
            <Select id="pr_status" value={form.status} onChange={(e) => set("status", e.target.value)}>
              {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </Select>
          </FormField>
          <FormField id="pr_start" label="Start date"><Input id="pr_start" type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} /></FormField>
          <FormField id="pr_deadline" label="Deadline" error={errors.deadline}><Input id="pr_deadline" type="date" value={form.deadline} onChange={(e) => set("deadline", e.target.value)} /></FormField>
          <FormField id="pr_value" label="Contract value" error={errors.contract_value} hint="For reference; has no accounting effect.">
            <div className="flex gap-2">
              <Input id="pr_value" inputMode="decimal" className="tabular text-right" value={form.contract_value} onChange={(e) => set("contract_value", e.target.value.trim())} />
              <Select aria-label="Currency" className="w-24" value={form.currency} onChange={(e) => set("currency", e.target.value)}>
                <option value="">Base</option>
                {currencies.data?.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
              </Select>
            </div>
          </FormField>
          <FormField id="pr_desc" label="Description" className="sm:col-span-2"><Textarea id="pr_desc" value={form.description} onChange={(e) => set("description", e.target.value)} /></FormField>

          <fieldset className="flex flex-col gap-2 rounded-md border p-3 sm:col-span-2">
            <legend className="px-1 text-sm font-medium">Team and default revenue split</legend>
            <p className="text-xs text-muted-foreground">The split pre-fills customer payments for this project; it can be changed per payment.</p>
            {members.map((m, i) => (
              <div key={i} className="grid grid-cols-[1fr_6rem_auto] gap-2 sm:grid-cols-[1fr_10rem_6rem_auto]">
                <EmployeePicker id={`m-${i}`} value={m.employee_id} onChange={(v) => setMembers(members.map((x, j) => (j === i ? { ...x, employee_id: v } : x)))} />
                <Input aria-label="Role" placeholder="Role" className="hidden sm:block" value={m.role} onChange={(e) => setMembers(members.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} />
                <div className="relative">
                  <Input aria-label="Default split %" inputMode="decimal" className="tabular pr-6 text-right" value={m.pct}
                    onChange={(e) => setMembers(members.map((x, j) => (j === i ? { ...x, pct: e.target.value.trim() } : x)))} />
                  <span className="pointer-events-none absolute right-2 top-2 text-sm text-muted-foreground">%</span>
                </div>
                <Button type="button" variant="ghost" size="icon" aria-label="Remove member" onClick={() => setMembers(members.filter((_, j) => j !== i))}><Trash2 /></Button>
              </div>
            ))}
            <div className="flex items-center justify-between">
              <Button type="button" variant="outline" size="sm" onClick={() => setMembers([...members, { employee_id: null, role: "", pct: "" }])}><Plus /> Add member</Button>
              <span className={`text-sm ${Number(pctTotal) > 100 ? "text-destructive" : "text-muted-foreground"}`}>Default split: {pctTotal}%</span>
            </div>
            {errors.members && <p role="alert" className="text-xs text-destructive">{errors.members}</p>}
          </fieldset>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending} disabled={!form.name.trim() || !form.ptype.category_id || Number(pctTotal) > 100}>{project ? "Save" : "Create project"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function ProjectsPage() {
  const can = useCan();
  const employees = useEmployees();
  const types = useCategories("project_type", true);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [dialog, setDialog] = useState<{ project: Project | null } | null>(null);
  const projects = useQuery({
    queryKey: ["projects", page, q, status],
    queryFn: () => api.get<Page<Project>>("/projects", { page, page_size: 25, q, status }),
    placeholderData: keepPreviousData,
  });
  const name = (id: string | null | undefined) => employees.data?.find((e) => e.id === id)?.full_name;
  const columns = useMemo<ColumnDef<Project, unknown>[]>(
    () => [
      { accessorKey: "name", header: "Project", cell: ({ row }) => (
        <button type="button" className="text-left" disabled={!can("projects.manage")} onClick={() => setDialog({ project: row.original })}>
          <span className="block font-medium hover:underline">{row.original.name}</span>
          <span className="block font-mono text-xs text-muted-foreground">{row.original.number}</span>
        </button>
      ) },
      { id: "type", header: "Type", cell: ({ row }) => types.data?.find((t) => t.id === row.original.project_type_category_id)?.name ?? "—" },
      { id: "manager", header: "Manager", cell: ({ row }) => name(row.original.manager_employee_id) ?? "—" },
      { id: "team", header: "Default split", enableSorting: false, cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.members.filter((m) => m.default_allocation_pct).map((m) => `${name(m.employee_id) ?? "?"} ${m.default_allocation_pct?.replace(/\.?0+$/, "")}%`).join(", ") || "—"}
        </span>
      ) },
      { id: "value", header: () => <span className="block text-right">Contract</span>, cell: ({ row }) => (
        <span className="tabular block text-right">{row.original.contract_value ? `${formatAmount(row.original.contract_value)} ${row.original.currency}` : "—"}</span>
      ) },
      { accessorKey: "deadline", header: "Deadline", cell: ({ row }) => formatDate(row.original.deadline) },
      { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge variant={STATUS[row.original.status]?.variant}>{STATUS[row.original.status]?.label}</Badge> },
    ],
    [can, types.data, employees.data], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <>
      <PageHeader title="Projects" description="Link customer payments to projects and set the default revenue split."
        actions={can("projects.manage") && <Button onClick={() => setDialog({ project: null })}><Plus /> New project</Button>} />
      <Card>
        <div className="flex flex-col gap-2 border-b p-3 sm:flex-row">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search" placeholder="Name or number" className="pl-8" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Status" className="sm:w-40" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </div>
        <DataTable columns={columns} data={projects.data?.items} isLoading={projects.isLoading} error={projects.error} getRowId={(p) => p.id}
          pagination={projects.data && { page, pageSize: 25, total: projects.data.total, onPageChange: setPage }}
          empty={<EmptyState title="No projects yet" />} />
      </Card>
      {dialog && <ProjectDialog project={dialog.project} onClose={() => setDialog(null)} />}
    </>
  );
}
