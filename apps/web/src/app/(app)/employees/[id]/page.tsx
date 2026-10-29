"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Receipt, Repeat } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { EmployeeSalaryView } from "@/components/salary/employee-salary";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useDepartments, useFormulas } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { CompAssignment, Employee } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const STATUS_VARIANT = { active: "success", on_leave: "warning", terminated: "muted" } as const;

function ChangeFormula({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const qc = useQueryClient();
  const formulas = useFormulas();
  const [formulaId, setFormulaId] = useState("");
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const save = useMutation({
    mutationFn: () => api.post("/comp-assignments", { employee_id: employee.id, formula_id: formulaId, effective_from: from, end_previous: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["comp-assignments", employee.id] });
      qc.invalidateQueries({ queryKey: ["employee-salary", employee.id] });
      toast.success("Salary formula updated");
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].join(" · ") : "Could not save"),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Salary formula for {employee.full_name}</DialogTitle>
          <DialogDescription>The current formula, if any, ends the day before the new one starts.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <FormField id="cf_formula" label="Formula" required>
            <Select id="cf_formula" value={formulaId} onChange={(e) => setFormulaId(e.target.value)}>
              <option value="">Choose…</option>
              {formulas.data?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </Select>
          </FormField>
          <FormField id="cf_from" label="From" required><Input id="cf_from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!formulaId || !from} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function EmployeePage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const departments = useDepartments();
  const [changing, setChanging] = useState(false);
  const employee = useQuery({ queryKey: ["employee", id], queryFn: () => api.get<Employee>(`/employees/${id}`) });
  const assignments = useQuery({
    queryKey: ["comp-assignments", id],
    queryFn: () => api.get<CompAssignment[]>("/comp-assignments", { employee_id: id }),
    enabled: can("comp_formulas.read"),
    retry: false,
  });
  if (employee.isError) return <ErrorState error={employee.error} onRetry={() => employee.refetch()} />;
  const e = employee.data;
  if (!e) return <TableSkeleton />;
  const dept = departments.data?.find((d) => d.id === e.department_id)?.name;

  return (
    <>
      <PageHeader
        title={e.full_name}
        description={[e.number, e.job_title, dept].filter(Boolean).join(" · ")}
        actions={
          <>
            {(can("payments.create") || can("reports.financial")) && (
              <Button variant="outline" asChild><Link href={`/accounting/payment-entries?employee_id=${e.id}`}><Receipt /> Payments</Link></Button>
            )}
            <Button variant="outline" asChild><Link href="/employees"><ArrowLeft /> Directory</Link></Button>
          </>
        }
      />
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Profile</CardTitle></CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
              <dt className="text-muted-foreground">Status</dt>
              <dd><Badge variant={STATUS_VARIANT[e.status as keyof typeof STATUS_VARIANT] ?? "default"}>{e.status.replace("_", " ")}</Badge></dd>
              <dt className="text-muted-foreground">Email</dt><dd>{e.email ?? "—"}</dd>
              <dt className="text-muted-foreground">Phone</dt><dd>{e.phone ?? "—"}</dd>
              <dt className="text-muted-foreground">Started</dt><dd>{formatDate(e.start_date)}</dd>
              {e.end_date && (<><dt className="text-muted-foreground">Left</dt><dd>{formatDate(e.end_date)}</dd></>)}
              <dt className="text-muted-foreground">Sign-in</dt><dd>{e.user_id ? "Linked" : "No account linked"}</dd>
            </dl>
          </CardContent>
        </Card>
        {can("comp_formulas.read") && (
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Salary formula</CardTitle>
              {can("comp_formulas.manage") && <Button size="sm" variant="outline" onClick={() => setChanging(true)}><Repeat /> Change</Button>}
            </CardHeader>
            <CardContent>
              {!assignments.data ? null : assignments.data.length === 0 ? (
                <p className="text-sm text-muted-foreground">No formula assigned. Revenue credited to {e.full_name} won&apos;t turn into salary until one is.</p>
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {assignments.data.map((a) => (
                    <li key={a.id} className="flex justify-between gap-3">
                      {can("comp_formulas.read") ? (
                        <Link href={`/employees/salary-formulas/${a.formula_id}`} className="font-medium hover:underline">{a.formula_name}</Link>
                      ) : <span className="font-medium">{a.formula_name}</span>}
                      <span className="text-muted-foreground">{formatDate(a.effective_from)} – {a.effective_to ? formatDate(a.effective_to) : "ongoing"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>
      {can("salary.read") && <EmployeeSalaryView employeeId={e.id} path={`/employees/${e.id}/salary`} showRevenue={can("revenue.read")} />}
      {changing && <ChangeFormula employee={e} onClose={() => setChanging(false)} />}
    </>
  );
}
