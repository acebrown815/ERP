"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download, Lock, LockOpen, Plus, Trash2, Wallet } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Breakdown, defaultPeriod, formatRate, PeriodSelect, periodRange, SalaryStatus } from "@/components/salary/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Badge, Card, CardContent } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { formatAmount, sign, subtract, sum } from "@/lib/money";
import { useCompany, useSalaryPeriods } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { SalaryAdjustment, SalaryBoard, SalaryBoardRow } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

// A file download from the API, not a page: a plain link on purpose.
const SALARY_CSV = `${"/api/v1"}/reports/employee-salary?format=csv`;

const errorText = (err: unknown) => (err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].join(" · ") : "Something went wrong");

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="tabular mt-1 text-2xl font-semibold">{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function AdjustmentDialog({ periodId, row, onClose }: { periodId: string; row: SalaryBoardRow; onClose: () => void }) {
  const qc = useQueryClient();
  const [kind, setKind] = useState<"bonus" | "deduction" | "correction">("bonus");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/salary-periods/${periodId}/adjustments`, { employee_id: row.employee_id, kind, amount, reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["salary-board", periodId] });
      qc.invalidateQueries({ queryKey: ["salary-adjustments", periodId] });
      toast.success("Adjustment added");
      onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Adjust {row.employee_name}&apos;s salary</DialogTitle>
          <DialogDescription>{row.period_label}. Added on top of the formula and never capped by its minimum or maximum.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <FormField id="adj_kind" label="Kind">
            <Select id="adj_kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="bonus">Bonus (adds)</option>
              <option value="deduction">Deduction (subtracts)</option>
              <option value="correction">Correction (+ or −)</option>
            </Select>
          </FormField>
          <FormField id="adj_amount" label="Amount" required hint={kind === "correction" ? "Use a minus sign to reduce." : "Enter a positive amount."}>
            <Input id="adj_amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </FormField>
          <FormField id="adj_reason" label="Reason" required hint="Shown to the employee on their statement.">
            <Input id="adj_reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!amount.trim() || !reason.trim()} loading={add.isPending} onClick={() => add.mutate()}>Add</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Detail({ row, periodId, editable }: { row: SalaryBoardRow; periodId: string; editable: boolean }) {
  const qc = useQueryClient();
  const adjustments = useQuery({
    queryKey: ["salary-adjustments", periodId, row.employee_id],
    queryFn: () => api.get<SalaryAdjustment[]>(`/salary-periods/${periodId}/adjustments`, { employee_id: row.employee_id }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/salary-adjustments/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["salary-board", periodId] });
      qc.invalidateQueries({ queryKey: ["salary-adjustments", periodId] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <div className="grid gap-6 bg-muted/30 px-4 py-4 md:grid-cols-2">
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">How it was calculated</p>
        <Breakdown components={row.components} total={row.calculated} />
        <p className="mt-2 text-xs text-muted-foreground">
          {row.formula_name ? `${row.formula_name}, version ${row.formula_version_no}` : "No salary formula assigned for this period."}
          {row.frozen && " · Frozen when the period was closed."}
        </p>
      </div>
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Adjustments</p>
        {!adjustments.data ? null : adjustments.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {adjustments.data.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2">
                <span><span className="capitalize">{a.kind}</span>: {a.reason} <span className="text-xs text-muted-foreground">· {formatDateTime(a.created_at)}</span></span>
                <span className="flex items-center gap-1">
                  <span className="tabular">{formatAmount(a.amount)}</span>
                  {editable && (
                    <Button variant="ghost" size="icon" aria-label={`Delete ${a.kind} ${a.reason}`} onClick={() => remove.mutate(a.id)}><Trash2 /></Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 text-sm">
          <Link className="text-primary hover:underline" href={`/employees/${row.employee_id}`}>Revenue detail and salary history →</Link>
        </p>
      </div>
    </div>
  );
}

export default function SalaryBoardPage() {
  const qc = useQueryClient();
  const can = useCan();
  const base = useCompany().data?.base_currency ?? "USD";
  const periods = useSalaryPeriods();
  const [periodId, setPeriodId] = useState<string>();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [adjusting, setAdjusting] = useState<SalaryBoardRow | null>(null);
  const [closing, setClosing] = useState(false);
  const [reopening, setReopening] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (!periodId && periods.data) setPeriodId(defaultPeriod(periods.data)?.id);
  }, [periods.data, periodId]);
  const board = useQuery({
    queryKey: ["salary-board", periodId],
    queryFn: () => api.get<SalaryBoard>(`/salary-periods/${periodId}/statements`),
    enabled: !!periodId,
  });
  const done = () => {
    qc.invalidateQueries({ queryKey: ["salary-periods"] });
    qc.invalidateQueries({ queryKey: ["salary-board"] });
  };
  const reopen = useMutation({
    mutationFn: () => api.post(`/salary-periods/${periodId}/reopen`, { reason }),
    onSuccess: () => {
      toast.success("Period reopened; statements are live again");
      setReopening(false);
      setReason("");
      done();
    },
    onError: (err) => toast.error(errorText(err)),
  });

  if (periods.isError) return <ErrorState error={periods.error} onRetry={() => periods.refetch()} />;
  const b = board.data;
  const p = b?.period;
  const editable = p?.status === "open" && can("salary.adjust");
  const owed = b ? sum(b.rows.map((r) => subtract(r.calculated, r.paid)).filter((d) => sign(d) > 0)) : "0";

  return (
    <>
      <PageHeader
        title="Salary"
        description="Each period's salary is calculated live from the revenue credited to each employee. Closing a period freezes it."
        actions={
          <>
            {periods.data && <PeriodSelect periods={periods.data} value={periodId} onChange={setPeriodId} />}
            <Button variant="outline" asChild><a href={SALARY_CSV} download><Download /> CSV</a></Button>
          </>
        }
      />
      {p && (
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">{p.label}</span>
          <span className="text-muted-foreground">{periodRange(p)}</span>
          {p.is_transition && <Badge variant="outline">Transition period</Badge>}
          {p.status === "closed" ? (
            <Badge variant="muted"><Lock className="size-3" /> Closed {formatDateTime(p.closed_at)}</Badge>
          ) : (
            <Badge variant="success"><LockOpen className="size-3" /> {p.is_current ? "Open · in progress" : p.is_future ? "Upcoming" : "Open"}</Badge>
          )}
          {p.reopen_reason && p.status === "open" && <span className="text-xs text-muted-foreground">Reopened: {p.reopen_reason}</span>}
          <span className="ml-auto flex gap-2">
            {p.status === "open" && can("salary.close_period") && (
              <Button size="sm" variant="outline" disabled={!b?.can_close} title={b?.close_blocker ?? undefined} onClick={() => setClosing(true)}>
                <Lock /> Close period
              </Button>
            )}
            {p.status === "closed" && can("salary.reopen_period") && (
              <Button size="sm" variant="ghost" onClick={() => setReopening(true)}><LockOpen /> Reopen</Button>
            )}
          </span>
        </div>
      )}
      {b && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi label="Revenue credited" value={`${formatAmount(b.total_revenue)} ${base}`} />
          <Kpi label="Salary calculated" value={`${formatAmount(b.total_calculated)} ${base}`} hint={p?.status === "open" ? "Projected while the period is open" : "Frozen"} />
          <Kpi label="Paid toward this period" value={`${formatAmount(b.total_paid)} ${base}`} />
          <Kpi label="Still owed for this period" value={`${formatAmount(owed)} ${base}`} />
        </div>
      )}
      <Card>
        {!b ? <TableSkeleton /> : b.rows.length === 0 ? (
          <EmptyState
            title="No salary in this period"
            description="Employees appear here once they have a salary formula or revenue credited in the period."
            action={can("comp_formulas.read") ? <Button variant="outline" asChild><Link href="/employees/salary-formulas">Salary formulas</Link></Button> : undefined}
          />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="w-8" />
                <TH>Employee</TH>
                <TH className="text-right">Revenue</TH>
                <TH className="text-right">Rate</TH>
                <TH className="text-right">Formula</TH>
                <TH className="text-right">Adjustments</TH>
                <TH className="text-right">Calculated</TH>
                <TH className="text-right">Paid</TH>
                <TH>Status</TH>
                <TH className="text-right" title="All periods, as of today">Balance</TH>
                <TH className="w-px" />
              </TR>
            </THead>
            <TBody>
              {b.rows.map((r) => {
                const expanded = open.has(r.employee_id);
                const due = subtract(r.calculated, r.paid);
                const payDue = sign(due) > 0;
                return (
                  <Fragment key={r.employee_id}>
                    <TR>
                      <TD>
                        <Button variant="ghost" size="icon" aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} details for ${r.employee_name}`}
                          onClick={() => setOpen((s) => { const n = new Set(s); if (expanded) n.delete(r.employee_id); else n.add(r.employee_id); return n; })}>
                          {expanded ? <ChevronDown /> : <ChevronRight />}
                        </Button>
                      </TD>
                      <TD>
                        <Link href={`/employees/${r.employee_id}`} className="font-medium hover:underline">{r.employee_name}</Link>
                        <p className="text-xs text-muted-foreground">{r.formula_name ?? <span className="text-warning">No formula</span>}</p>
                      </TD>
                      <TD className="tabular text-right">{formatAmount(r.revenue)}</TD>
                      <TD className="tabular text-right">{r.formula_name ? formatRate(r.rate) : "—"}</TD>
                      <TD className="tabular text-right">{formatAmount(r.formula_amount)}</TD>
                      <TD className="tabular text-right">{sign(r.adjustments_total) ? formatAmount(r.adjustments_total) : "—"}</TD>
                      <TD className="tabular text-right font-medium">{formatAmount(r.calculated)}</TD>
                      <TD className="tabular text-right">{formatAmount(r.paid)}</TD>
                      <TD><SalaryStatus status={r.status} /></TD>
                      <TD className={`tabular text-right ${sign(r.balance) > 0 ? "font-medium" : "text-muted-foreground"}`}>{formatAmount(r.balance)}</TD>
                      <TD className="whitespace-nowrap">
                        {editable && <Button variant="ghost" size="sm" onClick={() => setAdjusting(r)}><Plus /> Adjust</Button>}
                        {can("payments.create") && (payDue || sign(r.balance) > 0) && (
                          <Button variant="outline" size="sm" asChild>
                            <Link href={`/accounting/payment-entries/new?salary_employee=${r.employee_id}&amount=${payDue ? due : r.balance}${payDue ? `&period=${r.period_id}` : ""}`}>
                              <Wallet /> Pay
                            </Link>
                          </Button>
                        )}
                      </TD>
                    </TR>
                    {expanded && (
                      <tr className="border-b">
                        <td colSpan={11} className="p-0"><Detail row={r} periodId={b.period.id} editable={!!editable} /></td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
      <p className="mt-3 text-xs text-muted-foreground">
        Payments cover the period chosen on the payment, otherwise the oldest unpaid period first. Balance = all salary calculated so far minus all salary paid; negative means paid ahead.
      </p>

      {adjusting && periodId && <AdjustmentDialog periodId={periodId} row={adjusting} onClose={() => setAdjusting(null)} />}
      {closing && p && (
        <ConfirmDialog
          open
          onOpenChange={setClosing}
          title={`Close ${p.label}?`}
          description={
            <>
              Statements are frozen at today&apos;s figures ({formatAmount(b?.total_calculated)} {base} for {b?.rows.length} employees). Receipts dated {periodRange(p)} can&apos;t be submitted or cancelled until an administrator reopens the period. Salary can still be paid.
            </>
          }
          confirmLabel="Close period"
          onConfirm={async () => {
            await api.post(`/salary-periods/${p.id}/close`);
            toast.success(`${p.label} closed`);
            done();
          }}
        />
      )}
      {reopening && p && (
        <Dialog open onOpenChange={(o) => !o && setReopening(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reopen {p.label}?</DialogTitle>
              <DialogDescription>Statements become live again and are recalculated. The frozen figures and your reason stay in the audit log.</DialogDescription>
            </DialogHeader>
            <FormField id="reopen_reason" label="Reason" required><Input id="reopen_reason" value={reason} onChange={(e) => setReason(e.target.value)} /></FormField>
            <DialogFooter>
              <Button variant="outline" onClick={() => setReopening(false)}>Cancel</Button>
              <Button disabled={reason.trim().length < 3} loading={reopen.isPending} onClick={() => reopen.mutate()}>Reopen</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
