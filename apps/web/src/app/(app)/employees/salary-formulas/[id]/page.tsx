"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarPlus, Lock, Trash2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CategorySelect, type CategoryValue } from "@/components/erp/category-select";
import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { EmployeePicker } from "@/components/erp/pickers";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { FormulaEditor, fromDraft, toDraft, type Draft } from "@/components/salary/formula-editor";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { CompAssignment, Formula, FormulaDetail, FormulaVersion } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const today = () => new Date().toISOString().slice(0, 10);
const errorText = (err: unknown) =>
  err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].filter((v, i, a) => a.indexOf(v) === i).join(" · ") : "Something went wrong";

const BLANK: Draft = { mode: "linear_curve", below: "zero", rows: [{ a: "3000", b: "8" }, { a: "30000", b: "30" }], fixed: "", bonuses: [], min: "", max: "" };

function NewFormula() {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [type, setType] = useState<CategoryValue>({ category_id: null, other_text: "" });
  const [description, setDescription] = useState("");
  const [from, setFrom] = useState(today());
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () =>
      api.post<Formula>("/comp-formulas", {
        name,
        compensation_type_category_id: type.category_id,
        compensation_type_other_text: type.other_text || null,
        description: description || null,
        definition: fromDraft(draft),
        effective_from: from,
      }),
    onSuccess: (f) => {
      qc.invalidateQueries({ queryKey: ["comp-formulas"] });
      toast.success(`Created ${f.name}`);
      router.replace(`/employees/salary-formulas/${f.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      toast.error(errorText(err));
    },
  });
  return (
    <>
      <PageHeader title="New salary formula" actions={<Button variant="outline" asChild><Link href="/employees/salary-formulas"><ArrowLeft /> Back</Link></Button>} />
      <Card className="mb-6">
        <CardContent className="grid gap-4 py-5 md:grid-cols-2">
          <FormField id="name" label="Name" required error={errors.name}><Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Revenue Share 2027" /></FormField>
          <CategorySelect group="compensation_type" label="Type" value={type} onChange={setType} error={errors.compensation_type_category_id ?? errors.compensation_type_other_text} />
          <FormField id="from" label="Applies from" error={errors.effective_from} hint="The first salary period ending on or after this date uses it."><Input id="from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></FormField>
          <FormField id="desc" label="Description" className="md:col-span-2"><Textarea id="desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></FormField>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Rules</CardTitle></CardHeader>
        <CardContent><FormulaEditor value={draft} onChange={setDraft} /></CardContent>
      </Card>
      <div className="mt-6 flex justify-end">
        <Button disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>Create formula</Button>
      </div>
    </>
  );
}

function AssignDialog({ formula, onClose }: { formula: FormulaDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const [employee, setEmployee] = useState<string | null>(null);
  const [from, setFrom] = useState(today());
  const [notes, setNotes] = useState("");
  const assign = useMutation({
    mutationFn: () => api.post("/comp-assignments", { employee_id: employee, formula_id: formula.id, effective_from: from, notes: notes || null, end_previous: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["comp-formula", formula.id] });
      qc.invalidateQueries({ queryKey: ["comp-formulas"] });
      toast.success("Employee assigned");
      onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Assign to {formula.name}</DialogTitle>
          <DialogDescription>If the employee is on another formula, that one ends the day before.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <FormField id="a_emp" label="Employee" required><EmployeePicker id="a_emp" excludeHires value={employee} onChange={setEmployee} /></FormField>
          <FormField id="a_from" label="From" required><Input id="a_from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></FormField>
          <FormField id="a_notes" label="Notes"><Input id="a_notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!employee || !from} loading={assign.isPending} onClick={() => assign.mutate()}>Assign</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EndDialog({ assignment, onClose, formulaId }: { assignment: CompAssignment; onClose: () => void; formulaId: string }) {
  const qc = useQueryClient();
  const [to, setTo] = useState(assignment.effective_to ?? today());
  const save = useMutation({
    mutationFn: (effective_to: string | null) => api.patch(`/comp-assignments/${assignment.id}`, { version: assignment.version, effective_to }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["comp-formula", formulaId] });
      qc.invalidateQueries({ queryKey: ["comp-formulas"] });
      toast.success("Assignment updated");
      onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>End date for {assignment.employee_name}</DialogTitle>
          <DialogDescription>The formula stops applying after this date.</DialogDescription>
        </DialogHeader>
        <FormField id="e_to" label="Last day"><Input id="e_to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></FormField>
        <DialogFooter>
          {assignment.effective_to && <Button variant="ghost" className="mr-auto" loading={save.isPending} onClick={() => save.mutate(null)}>Remove end date</Button>}
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!to} loading={save.isPending} onClick={() => save.mutate(to)}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FormulaView({ id }: { id: string }) {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can("comp_formulas.manage");
  const q = useQuery({ queryKey: ["comp-formula", id], queryFn: () => api.get<FormulaDetail>(`/comp-formulas/${id}`) });
  const [versionId, setVersionId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [from, setFrom] = useState(today());
  const [notes, setNotes] = useState("");
  const [meta, setMeta] = useState<{ name: string; description: string } | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [ending, setEnding] = useState<CompAssignment | null>(null);
  const [deleting, setDeleting] = useState<FormulaVersion | CompAssignment | null>(null);

  const f = q.data;
  useEffect(() => {
    if (f && !versionId) setVersionId(f.current?.id ?? f.versions[0]?.id ?? null);
  }, [f, versionId]);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["comp-formula", id] });
    qc.invalidateQueries({ queryKey: ["comp-formulas"] });
  };

  const addVersion = useMutation({
    mutationFn: () => api.post<FormulaVersion>(`/comp-formulas/${id}/versions`, { definition: fromDraft(editing!), effective_from: from, notes: notes || null }),
    onSuccess: (v) => {
      toast.success(`Version ${v.version_no} saved, applies from ${formatDate(v.effective_from)}`);
      setEditing(null);
      setNotes("");
      setVersionId(v.id);
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const update = useMutation({
    mutationFn: (changes: Record<string, unknown>) => api.patch<Formula>(`/comp-formulas/${id}`, { version: f!.version, ...changes }),
    onSuccess: () => {
      setMeta(null);
      refresh();
      toast.success("Formula updated");
    },
    onError: (err) => toast.error(errorText(err)),
  });

  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!f) return <TableSkeleton />;
  const shown = f.versions.find((v) => v.id === versionId) ?? f.current ?? f.versions[0];

  return (
    <>
      <PageHeader
        title={f.name}
        description={f.description ?? undefined}
        actions={
          <>
            <Button variant="outline" asChild><Link href="/employees/salary-formulas"><ArrowLeft /> All formulas</Link></Button>
            {manage && <Button variant="outline" onClick={() => setMeta({ name: f.name, description: f.description ?? "" })}>Edit details</Button>}
            {manage && (
              <Button variant="outline" loading={update.isPending} onClick={() => update.mutate({ is_active: !f.is_active })}>
                {f.is_active ? "Deactivate" : "Activate"}
              </Button>
            )}
          </>
        }
      />
      {!f.is_active && <p className="mb-4 text-sm text-muted-foreground"><Badge variant="muted">Inactive</Badge> It can&apos;t be assigned to anyone.</p>}

      <Card className="mb-6">
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>{editing ? "New version" : "Rules"}</CardTitle>
            <CardDescription>
              {editing
                ? "Applies to every salary period ending on or after the date. Earlier periods keep the previous version."
                : shown && <>Version {shown.version_no}, applies from {formatDate(shown.effective_from)}{shown.notes ? ` · ${shown.notes}` : ""}</>}
            </CardDescription>
          </div>
          {!editing && (
            <div className="flex flex-wrap items-center gap-2">
              {f.versions.length > 1 && (
                <Select aria-label="Version" className="w-auto" value={shown?.id} onChange={(e) => setVersionId(e.target.value)}>
                  {f.versions.map((v) => <option key={v.id} value={v.id}>v{v.version_no} · from {formatDate(v.effective_from)}{v.id === f.current?.id ? " (current)" : ""}</option>)}
                </Select>
              )}
              {shown?.is_locked && <Badge variant="muted"><Lock className="size-3" /> Used by a closed period</Badge>}
              {manage && shown && !shown.is_locked && f.versions.length > 1 && (
                <Button variant="ghost" size="sm" onClick={() => setDeleting(shown)}><Trash2 /> Delete version</Button>
              )}
              {manage && shown && <Button size="sm" onClick={() => setEditing(toDraft(shown.definition))}><CalendarPlus /> Change from a date…</Button>}
            </div>
          )}
        </CardHeader>
        <CardContent>
          {editing ? (
            <>
              <FormulaEditor value={editing} onChange={setEditing} />
              <div className="mt-6 grid gap-4 border-t pt-4 md:grid-cols-[12rem_1fr_auto] md:items-end">
                <FormField id="v_from" label="Applies from" required><Input id="v_from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></FormField>
                <FormField id="v_notes" label="What changed"><Input id="v_notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Added a $10k point at 15%" /></FormField>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
                  <Button loading={addVersion.isPending} onClick={() => addVersion.mutate()}>Save version</Button>
                </div>
              </div>
            </>
          ) : shown ? (
            <FormulaEditor key={shown.id} value={toDraft(shown.definition)} onChange={() => {}} readOnly />
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Employees</CardTitle>
            <CardDescription>Who is paid with this formula, and when.</CardDescription>
          </div>
          {manage && f.is_active && <Button size="sm" onClick={() => setAssigning(true)}><UserPlus /> Assign employee</Button>}
        </CardHeader>
        <CardContent>
          {f.assignments.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nobody yet.{manage && " Assign employees so their revenue turns into salary."}</p>
          ) : (
            <Table>
              <THead><TR><TH>Employee</TH><TH>From</TH><TH>Until</TH><TH>Notes</TH>{manage && <TH className="w-px" />}</TR></THead>
              <TBody>
                {f.assignments.map((a) => (
                  <TR key={a.id}>
                    <TD><Link className="font-medium hover:underline" href={`/employees/${a.employee_id}`}>{a.employee_name}</Link></TD>
                    <TD>{formatDate(a.effective_from)}</TD>
                    <TD>{a.effective_to ? formatDate(a.effective_to) : <span className="text-muted-foreground">ongoing</span>}</TD>
                    <TD className="text-muted-foreground">{a.notes}</TD>
                    {manage && (
                      <TD className="whitespace-nowrap">
                        <Button variant="ghost" size="sm" onClick={() => setEnding(a)}>End…</Button>
                        <Button variant="ghost" size="icon" aria-label={`Delete assignment for ${a.employee_name}`} onClick={() => setDeleting(a)}><Trash2 /></Button>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {assigning && <AssignDialog formula={f} onClose={() => setAssigning(false)} />}
      {ending && <EndDialog assignment={ending} formulaId={f.id} onClose={() => setEnding(null)} />}
      {deleting && (
        <ConfirmDialog
          open
          onOpenChange={(o) => !o && setDeleting(null)}
          destructive
          title={"version_no" in deleting ? `Delete version ${deleting.version_no}?` : `Delete ${deleting.employee_name}'s assignment?`}
          description={"version_no" in deleting
            ? "Periods it covered will use the previous version. Versions used by a closed period can't be deleted."
            : "Use this only for a mistaken assignment. To stop paying with this formula, set an end date instead."}
          confirmLabel="Delete"
          onConfirm={async () => {
            await api.delete("version_no" in deleting ? `/comp-formula-versions/${deleting.id}` : `/comp-assignments/${deleting.id}`);
            if ("version_no" in deleting) setVersionId(null);
            refresh();
            setDeleting(null);
          }}
        />
      )}
      {meta && (
        <Dialog open onOpenChange={(o) => !o && setMeta(null)}>
          <DialogContent>
            <DialogHeader><DialogTitle>Edit details</DialogTitle></DialogHeader>
            <div className="flex flex-col gap-4">
              <FormField id="m_name" label="Name" required><Input id="m_name" value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></FormField>
              <FormField id="m_desc" label="Description"><Textarea id="m_desc" rows={3} value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></FormField>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setMeta(null)}>Cancel</Button>
              <Button disabled={!meta.name.trim()} loading={update.isPending} onClick={() => update.mutate({ name: meta.name, description: meta.description || null })}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

export default function FormulaPage() {
  const { id } = useParams<{ id: string }>();
  return id === "new" ? <NewFormula /> : <FormulaView id={id} />;
}

