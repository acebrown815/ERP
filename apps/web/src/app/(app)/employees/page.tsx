"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { CategorySelect, useCategories } from "@/components/erp/category-select";
import { Combobox } from "@/components/erp/combobox";
import { DataTable } from "@/components/erp/data-table";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useDepartments } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { Department, Employee, Page, User } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const STATUS: Record<string, { label: string; variant: "success" | "warning" | "muted" }> = {
  active: { label: "Active", variant: "success" },
  on_leave: { label: "On leave", variant: "warning" },
  terminated: { label: "Left", variant: "muted" },
};

function EmployeeDialog({ employee, onClose }: { employee: Employee | null; onClose: () => void }) {
  const qc = useQueryClient();
  const can = useCan();
  const departments = useDepartments();
  const users = useQuery({
    queryKey: ["users", "for-employee-link"],
    queryFn: async () => (await api.get<Page<User>>("/users", { page_size: 200 })).items,
    enabled: can("users.manage"),
  });
  const [form, setForm] = useState({
    full_name: employee?.full_name ?? "",
    email: employee?.email ?? "",
    phone: employee?.phone ?? "",
    job_title: employee?.job_title ?? "",
    department_id: employee?.department_id ?? "",
    employment: { category_id: employee?.employment_type_category_id ?? null, other_text: employee?.employment_type_other_text ?? "" },
    status: employee?.status ?? "active",
    start_date: employee?.start_date ?? new Date().toISOString().slice(0, 10),
    end_date: employee?.end_date ?? "",
    user_id: employee?.user_id ?? null,
    notes: employee?.notes ?? "",
  });
  const [newDept, setNewDept] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const body = {
        full_name: form.full_name, email: form.email || null, phone: form.phone || null, job_title: form.job_title || null,
        department_id: form.department_id || null, employment_type_category_id: form.employment.category_id,
        employment_type_other_text: form.employment.other_text || null, status: form.status, start_date: form.start_date,
        end_date: form.end_date || null, notes: form.notes || null, ...(can("users.manage") ? { user_id: form.user_id } : {}),
      };
      return employee ? api.patch<Employee>(`/employees/${employee.id}`, { ...body, version: employee.version }) : api.post<Employee>("/employees", body);
    },
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success(employee ? "Saved" : `${e.full_name} added (${e.number})`);
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        if (!err.errors.length) toast.error(err.message);
      }
    },
  });
  const addDept = useMutation({
    mutationFn: () => api.post<Department>("/departments", { name: newDept }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["departments"] });
      set("department_id", d.id);
      setNewDept("");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not add"),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide>
        <DialogHeader><DialogTitle>{employee ? `Edit ${employee.full_name}` : "New employee"}</DialogTitle></DialogHeader>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <FormField id="e_name" label="Full name" required error={errors.full_name}><Input id="e_name" value={form.full_name} onChange={(e) => set("full_name", e.target.value)} /></FormField>
          <FormField id="e_title" label="Job title"><Input id="e_title" value={form.job_title} onChange={(e) => set("job_title", e.target.value)} /></FormField>
          <FormField id="e_email" label="Email" error={errors.email}><Input id="e_email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} /></FormField>
          <FormField id="e_phone" label="Phone"><Input id="e_phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} /></FormField>
          <CategorySelect group="employment_type" label="Employment type" required value={form.employment} onChange={(v) => set("employment", v)}
            error={errors.employment_type_category_id ?? errors.employment_type_other_text} />
          <FormField id="e_dept" label="Department">
            <Select id="e_dept" value={form.department_id} onChange={(e) => set("department_id", e.target.value)}>
              <option value="">—</option>
              {departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
            {can("employees.manage") && (
              <div className="flex gap-2">
                <Input aria-label="New department" placeholder="New department…" value={newDept} onChange={(e) => setNewDept(e.target.value)} />
                <Button type="button" variant="outline" size="sm" className="h-9" disabled={!newDept.trim()} loading={addDept.isPending} onClick={() => addDept.mutate()}>Add</Button>
              </div>
            )}
          </FormField>
          <FormField id="e_start" label="Start date" required error={errors.start_date}><Input id="e_start" type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} /></FormField>
          <FormField id="e_end" label="End date" error={errors.end_date}><Input id="e_end" type="date" value={form.end_date} onChange={(e) => set("end_date", e.target.value)} /></FormField>
          <FormField id="e_status" label="Status">
            <Select id="e_status" value={form.status} onChange={(e) => set("status", e.target.value)}>
              {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </Select>
          </FormField>
          {can("users.manage") && (
            <FormField id="e_user" label="Sign-in account" hint="Lets them see their own revenue and salary." error={errors.user_id}>
              <Combobox id="e_user" value={form.user_id} onChange={(v) => set("user_id", v)} placeholder="Not linked"
                options={(users.data ?? []).map((u) => ({ value: u.id, label: u.full_name, hint: u.email }))} />
            </FormField>
          )}
          <FormField id="e_notes" label="Notes" className="sm:col-span-2"><Textarea id="e_notes" value={form.notes} onChange={(e) => set("notes", e.target.value)} /></FormField>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending} disabled={!form.full_name.trim() || !form.employment.category_id}>{employee ? "Save" : "Add employee"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function EmployeesPage() {
  const can = useCan();
  const departments = useDepartments();
  const types = useCategories("employment_type", true);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("active");
  const [dialog, setDialog] = useState<{ employee: Employee | null } | null>(null);
  const employees = useQuery({
    queryKey: ["employees", page, q, status],
    queryFn: () => api.get<Page<Employee>>("/employees", { page, page_size: 25, q, status }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<Employee, unknown>[]>(
    () => [
      {
        accessorKey: "full_name",
        header: "Name",
        cell: ({ row }) => (
          <Link href={`/employees/${row.original.id}`} className="block">
            <span className="block font-medium hover:underline">{row.original.full_name}</span>
            <span className="block text-xs text-muted-foreground">{row.original.job_title ?? row.original.email ?? ""}</span>
          </Link>
        ),
      },
      { accessorKey: "number", header: "Number", cell: ({ getValue }) => <span className="font-mono text-xs">{getValue() as string}</span> },
      { id: "dept", header: "Department", cell: ({ row }) => departments.data?.find((d) => d.id === row.original.department_id)?.name ?? "—" },
      { id: "type", header: "Type", cell: ({ row }) => {
        const t = types.data?.find((c) => c.id === row.original.employment_type_category_id);
        return t ? (row.original.employment_type_other_text ? `${t.name}: ${row.original.employment_type_other_text}` : t.name) : "—";
      } },
      { accessorKey: "start_date", header: "Started", cell: ({ row }) => formatDate(row.original.start_date) },
      { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge variant={STATUS[row.original.status]?.variant}>{STATUS[row.original.status]?.label}</Badge> },
      { id: "user", header: "Sign-in", cell: ({ row }) => (row.original.user_id ? <Badge variant="outline">Linked</Badge> : <span className="text-xs text-muted-foreground">—</span>) },
      ...(can("employees.manage")
        ? [{ id: "edit", header: "", cell: ({ row }: { row: { original: Employee } }) => (
            <Button variant="ghost" size="sm" onClick={() => setDialog({ employee: row.original })}>Edit</Button>
          ) } as ColumnDef<Employee, unknown>]
        : []),
    ],
    [can, departments.data, types.data],
  );

  return (
    <>
      <PageHeader title="Employees" description="Everyone who can be credited with revenue or paid a salary."
        actions={can("employees.manage") && <Button onClick={() => setDialog({ employee: null })}><Plus /> New employee</Button>} />
      <Card>
        <div className="flex flex-col gap-2 border-b p-3 sm:flex-row">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search" placeholder="Name, email, title" className="pl-8" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Status" className="sm:w-40" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All</option>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </div>
        <DataTable columns={columns} data={employees.data?.items} isLoading={employees.isLoading} error={employees.error} getRowId={(e) => e.id}
          pagination={employees.data && { page, pageSize: 25, total: employees.data.total, onPageChange: setPage }}
          empty={<EmptyState title="No employees" description="Add people here or import a CSV under Settings → Data Import." />} />
      </Card>
      {dialog && <EmployeeDialog employee={dialog.employee} onClose={() => setDialog(null)} />}
    </>
  );
}
