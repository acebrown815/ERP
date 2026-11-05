"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { CategorySelect } from "@/components/erp/category-select";
import { FormField } from "@/components/erp/form-field";
import { EmployeePicker, HirePicker, PartyPicker } from "@/components/erp/pickers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { sum } from "@/lib/money";
import { useCurrencies } from "@/lib/queries";
import { useCan, useMe } from "@/lib/session";
import type { Project } from "@/lib/types";

export const PROJECT_STATUS: Record<string, { label: string; variant: "success" | "warning" | "muted" | "default" }> = {
  planned: { label: "Planned", variant: "default" },
  active: { label: "Active", variant: "success" },
  on_hold: { label: "On hold", variant: "warning" },
  completed: { label: "Completed", variant: "muted" },
  cancelled: { label: "Cancelled", variant: "muted" },
};

type MemberDraft = { employee_id: string | null; role: string; pct: string };

/**
 * Staff (full) edit everything. An employee running their own project (own) edits the work only, so the money fields
 * and the team aren't shown or sent; the API enforces the same limits. Restricted access never opens this dialog.
 */
export function ProjectDialog({ project, onClose }: { project: Project | null; onClose: () => void }) {
  const qc = useQueryClient();
  const me = useMe();
  const can = useCan();
  const currencies = useCurrencies();
  const mode = project?.edit_mode ?? (can("projects.manage") ? "full" : "own");
  const staff = mode === "full";
  const [form, setForm] = useState({
    name: project?.name ?? "",
    customer_party_id: project?.customer_party_id ?? null,
    manager_employee_id: project?.manager_employee_id ?? null,
    hire_employee_id: project?.hire_employee_id ?? null,
    ptype: { category_id: project?.project_type_category_id ?? null, other_text: project?.project_type_other_text ?? "" },
    start_date: project?.start_date ?? "",
    deadline: project?.deadline ?? "",
    contract_value: project?.contract_value ? project.contract_value.replace(/\.?0+$/, "") : "",
    currency: project?.currency ?? "",
    status: project?.status ?? "active",
    priority: project?.priority ?? "medium",
    budget: project?.budget ? project.budget.replace(/\.?0+$/, "") : "",
    completion_override: project?.completion_override ? project.completion_override.replace(/\.?0+$/, "") : "",
    description: project?.description ?? "",
  });
  const [members, setMembers] = useState<MemberDraft[]>(
    (project?.members ?? []).map((m) => ({ employee_id: m.employee_id, role: m.role ?? "", pct: m.default_allocation_pct?.replace(/\.?0+$/, "") ?? "" })),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const pctTotal = sum(members.map((m) => m.pct));
  const hireChanged = !!project?.hire_employee_id && form.hire_employee_id !== project.hire_employee_id;

  const save = useMutation({
    mutationFn: async () => {
      const work = {
        name: form.name,
        project_type_category_id: form.ptype.category_id,
        project_type_other_text: form.ptype.other_text || null,
        start_date: form.start_date || null,
        deadline: form.deadline || null,
        status: form.status,
        description: form.description || null,
        priority: form.priority,
        completion_override: form.completion_override || null,
      };
      const body =
        mode === "full"
          ? {
              ...work,
              customer_party_id: form.customer_party_id,
              manager_employee_id: form.manager_employee_id,
              hire_employee_id: form.hire_employee_id,
              contract_value: form.contract_value || null,
              currency: form.currency || null,
              budget: form.budget || null,
              // Saved together with the project, so the rules are checked on the end result.
              members: members
                .filter((m) => m.employee_id)
                .map((m) => ({ employee_id: m.employee_id, role: m.role || null, default_allocation_pct: m.pct || null })),
            }
          : me.can_select_hire
            ? { ...work, hire_employee_id: form.hire_employee_id }
            : work;
      return project ? api.patch<Project>(`/projects/${project.id}`, { ...body, version: project.version }) : api.post<Project>("/projects", body);
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["project", p.id] });
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
          <DialogDescription>
            {staff
              ? "Details, budget and team. The team's default split pre-fills customer payments for this project."
              : mode === "own"
                ? me.can_select_hire
                  ? "You're the project manager and earn its revenue. If you select a hire, what they're paid comes off your revenue."
                  : "You're the project manager and earn its revenue."
                : ""}
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <FormField id="pr_name" label="Name" required error={errors.name} className="sm:col-span-2"><Input id="pr_name" value={form.name} onChange={(e) => set("name", e.target.value)} /></FormField>
          {staff && (
            <FormField id="pr_customer" label="Customer" error={errors.customer_party_id}>
              <PartyPicker id="pr_customer" kinds={["customer", "other"]} value={form.customer_party_id} onChange={(v) => set("customer_party_id", v)} />
            </FormField>
          )}
          {staff && (
            <FormField id="pr_manager" label="Project manager" error={errors.manager_employee_id} hint="Earns the revenue, and pays the hire if there is one.">
              <EmployeePicker id="pr_manager" excludeHires value={form.manager_employee_id} onChange={(v) => set("manager_employee_id", v)} />
            </FormField>
          )}
          {mode === "own" && (
            <FormField id="pr_manager" label="Project manager">
              <Input id="pr_manager" readOnly value={project?.manager_name ?? me.full_name} />
            </FormField>
          )}
          {me.can_select_hire && (
            <FormField id="pr_hire" label="Hire" error={errors.hire_employee_id}
              hint={hireChanged ? "Pay anything owed to the current hire first: only a project's current hire can be paid on it." : "Optional: someone hired to help run this project."}>
              <HirePicker id="pr_hire" value={form.hire_employee_id} currentName={project?.hire_name} onChange={(v) => set("hire_employee_id", v)} />
            </FormField>
          )}
          <CategorySelect group="project_type" label="Project type" required value={form.ptype} onChange={(v) => set("ptype", v)}
            error={errors.project_type_category_id ?? errors.project_type_other_text} />
          <FormField id="pr_status" label="Status">
            <Select id="pr_status" value={form.status} onChange={(e) => set("status", e.target.value)}>
              {Object.entries(PROJECT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </Select>
          </FormField>
          <FormField id="pr_start" label="Start date"><Input id="pr_start" type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} /></FormField>
          <FormField id="pr_deadline" label="Deadline" error={errors.deadline}><Input id="pr_deadline" type="date" value={form.deadline} onChange={(e) => set("deadline", e.target.value)} /></FormField>
          {staff && (
            <FormField id="pr_value" label="Contract value" error={errors.contract_value} hint="For reference; has no accounting effect.">
              <div className="flex gap-2">
                <Input id="pr_value" inputMode="decimal" className="tabular text-right" value={form.contract_value} onChange={(e) => set("contract_value", e.target.value.trim())} />
                <Select aria-label="Currency" className="w-24" value={form.currency} onChange={(e) => set("currency", e.target.value)}>
                  <option value="">Base</option>
                  {currencies.data?.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
                </Select>
              </div>
            </FormField>
          )}
          <FormField id="pr_priority" label="Priority">
            <Select id="pr_priority" value={form.priority} onChange={(e) => set("priority", e.target.value)}>
              {["low", "medium", "high", "urgent"].map((p) => <option key={p} value={p}>{p[0]!.toUpperCase() + p.slice(1)}</option>)}
            </Select>
          </FormField>
          {staff && (
            <FormField id="pr_budget" label="Budget" error={errors.budget} hint="Limit for expenses + salary cost (base currency).">
              <Input id="pr_budget" inputMode="decimal" className="tabular text-right" value={form.budget} onChange={(e) => set("budget", e.target.value.trim())} />
            </FormField>
          )}
          <FormField id="pr_completion" label="Completion % (manual)" error={errors.completion_override} hint="Leave empty to calculate from tasks.">
            <Input id="pr_completion" inputMode="decimal" className="tabular text-right" value={form.completion_override} onChange={(e) => set("completion_override", e.target.value.trim())} />
          </FormField>
          <FormField id="pr_desc" label="Description" className="sm:col-span-2"><Textarea id="pr_desc" value={form.description} onChange={(e) => set("description", e.target.value)} /></FormField>

          {staff && (
            <fieldset className="flex flex-col gap-2 rounded-md border p-3 sm:col-span-2">
              <legend className="px-1 text-sm font-medium">Team and default revenue split</legend>
              <p className="text-xs text-muted-foreground">The split pre-fills customer payments for this project; it can be changed per payment.</p>
              {members.map((m, i) => (
                <div key={i} className="grid grid-cols-[1fr_6rem_auto] gap-2 sm:grid-cols-[1fr_10rem_6rem_auto]">
                  <EmployeePicker id={`m-${i}`} excludeHires value={m.employee_id} onChange={(v) => setMembers(members.map((x, j) => (j === i ? { ...x, employee_id: v } : x)))} />
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
          )}
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={save.isPending}
              disabled={!form.name.trim() || !form.ptype.category_id || Number(pctTotal) > 100}>
              {project ? "Save" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
