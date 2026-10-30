"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CopyPlus, Landmark, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { useCategories } from "@/components/erp/category-select";
import { FormField } from "@/components/erp/form-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { currencyPrecision, useCompany, useCurrencies, usePaymentAccounts } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { JournalEntry, PaymentEntry } from "@/lib/types";
import { formatDate, formatDateTime } from "@/lib/utils";

export function StatusBadge({ status }: { status: string }) {
  const variant = status === "submitted" ? "success" : status === "cancelled" ? "muted" : "warning";
  return <Badge variant={variant}>{status === "submitted" ? "Submitted" : status === "cancelled" ? "Cancelled" : "Draft"}</Badge>;
}

function JournalTable({ id, title }: { id: string; title: string }) {
  const je = useQuery({ queryKey: ["journal-entry", id], queryFn: () => api.get<JournalEntry>(`/journal-entries/${id}`) });
  if (!je.data) return null;
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{title}</CardTitle>
        <span className="font-mono text-xs text-muted-foreground">{je.data.number}</span>
      </CardHeader>
      <CardContent>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 text-left font-medium">Account</th>
              <th className="py-1.5 text-right font-medium">Debit</th>
              <th className="py-1.5 text-right font-medium">Credit</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {je.data.lines.map((l) => (
              <tr key={l.line_no} className="border-b last:border-0">
                <td className="py-1.5">
                  <span className="font-mono text-xs text-muted-foreground">{l.account_code}</span> {l.account_name}
                </td>
                <td className="py-1.5 text-right">{Number(l.debit) ? formatAmount(l.debit) : ""}</td>
                <td className="py-1.5 text-right">{Number(l.credit) ? formatAmount(l.credit) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children ?? "—"}</dd>
    </div>
  );
}

export function PaymentEntryView({ entry }: { entry: PaymentEntry }) {
  const qc = useQueryClient();
  const router = useRouter();
  const can = useCan();
  const company = useCompany();
  const currencies = useCurrencies();
  const seesLedger = can("journals.post") || can("reports.financial");
  const accounts = usePaymentAccounts(true, can("payments.create") || can("reports.financial"));
  const methods = useCategories("payment_method", true);
  const purposes = useCategories("payment_purpose", true);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const base = company.data?.base_currency ?? "USD";
  const precision = currencyPrecision(currencies.data, entry.currency);
  const name = (id: string | null | undefined) => accounts.data?.find((a) => a.id === id)?.name;
  const cat = (list: typeof methods.data, id: string | null | undefined, other?: string | null) => {
    const c = list?.find((x) => x.id === id);
    return c ? (other ? `${c.path}: ${other}` : c.path) : undefined;
  };

  const refresh = (pe: PaymentEntry) => {
    qc.setQueryData(["payment-entry", pe.id], pe);
    qc.invalidateQueries({ queryKey: ["payment-entries"] });
    qc.invalidateQueries({ queryKey: ["accounts"] });
  };
  const cancel = useMutation({
    mutationFn: () => api.post<PaymentEntry>(`/payment-entries/${entry.id}/cancel`, { reason }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (pe) => {
      refresh(pe);
      setCancelOpen(false);
      toast.success(`${pe.number} cancelled; a reversal was posted on the same date`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not cancel"),
  });
  const amend = useMutation({
    mutationFn: () => api.post<PaymentEntry>(`/payment-entries/${entry.id}/amend`),
    onSuccess: (pe) => {
      toast.success(`Draft ${pe.number} created from ${entry.number}`);
      router.push(`/accounting/payment-entries/${pe.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not amend"),
  });
  const reconcile = useMutation({
    mutationFn: () => api.post<PaymentEntry>(`/payment-entries/${entry.id}/reconcile`, { reconciled: !entry.reconciled_at }),
    onSuccess: refresh,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update"),
  });

  const direction = entry.direction === "receive" ? "Received" : entry.direction === "pay" ? "Paid" : "Transferred";

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="flex flex-col gap-6">
        {entry.status === "cancelled" && (
          <div className="rounded-md border bg-muted/50 px-4 py-3 text-sm">
            <strong>Cancelled</strong> {formatDateTime(entry.cancelled_at)}: {entry.cancel_reason}. The ledger entry was reversed on
            its original date, so this payment no longer appears in balances or reports.
          </div>
        )}
        <Card>
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm text-muted-foreground">
                {direction} on {formatDate(entry.posting_date)}
              </p>
              {entry.my_share != null ? (
                // Employee view of a payment split between employees: their share is what matters to them.
                <>
                  <p className="tabular text-3xl font-semibold tracking-tight">
                    {formatAmount(entry.my_share)} <span className="text-lg text-muted-foreground">{base}</span>
                  </p>
                  <p className="tabular text-sm text-muted-foreground">
                    Your share of {formatAmount(entry.amount, precision)} {entry.currency}
                  </p>
                </>
              ) : (
                <p className="tabular text-3xl font-semibold tracking-tight">
                  {formatAmount(entry.amount, precision)} <span className="text-lg text-muted-foreground">{entry.currency}</span>
                </p>
              )}
              {entry.my_share == null && entry.currency !== base && entry.base_amount && (
                <p className="tabular text-sm text-muted-foreground">
                  = {formatAmount(entry.base_amount)} {base} at {(entry.exchange_rate ?? "").replace(/\.?0+$/, "")}
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge status={entry.status} />
              {entry.reconciled_at && (
                <Badge variant="outline">
                  <ShieldCheck className="size-3" /> Checked against bank
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <dl className="divide-y">
              {entry.party_name && <Row label={entry.direction === "receive" ? "From" : "To"}>{entry.party_name}</Row>}
              {entry.paid_from_payment_account_id && <Row label="Paid from">{name(entry.paid_from_payment_account_id)}</Row>}
              {entry.paid_to_payment_account_id && <Row label="Received into">{name(entry.paid_to_payment_account_id)}</Row>}
              {entry.received_amount && entry.received_currency !== entry.currency && (
                <Row label="Amount received">
                  <span className="tabular">
                    {formatAmount(entry.received_amount, currencyPrecision(currencies.data, entry.received_currency))}{" "}
                    {entry.received_currency}
                  </span>
                </Row>
              )}
              <Row label="Purpose">{cat(purposes.data, entry.purpose_category_id, entry.purpose_other_text)}</Row>
              <Row label="Method">{cat(methods.data, entry.method_category_id, entry.method_other_text)}</Row>
              {Number(entry.fee_amount) > 0 && (
                <Row label="Fee">
                  <span className="tabular">
                    {formatAmount(entry.fee_amount, precision)} {entry.currency}
                  </span>{" "}
                  ({entry.fee_paid_by === "company" ? "paid by us" : "paid by the other side"})
                </Row>
              )}
              {entry.project_name && <Row label="Project">{entry.project_name}</Row>}
              {entry.salary_period_label && <Row label="Salary for">{entry.salary_period_label}</Row>}
              {entry.reference_no && <Row label="Reference">{entry.reference_no}</Row>}
              {entry.description && <Row label="Description">{entry.description}</Row>}
              {entry.amended_from_id && (
                <Row label="Amends">
                  <Link className="text-primary hover:underline" href={`/accounting/payment-entries/${entry.amended_from_id}`}>
                    cancelled payment
                  </Link>
                </Row>
              )}
              <Row label="Submitted">{formatDateTime(entry.submitted_at)}</Row>
            </dl>
          </CardContent>
        </Card>

        {entry.allocations.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>{entry.direction === "pay" ? "Employee expense split" : "Employee revenue split"}</CardTitle>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <tbody className="tabular">
                  {entry.allocations.map((a) => (
                    <tr key={a.employee_id} className="border-b last:border-0">
                      <td className="py-1.5">{a.employee_name}</td>
                      <td className="py-1.5 text-right text-muted-foreground">{a.percent ? `${a.percent.replace(/\.?0+$/, "")}%` : ""}</td>
                      <td className="py-1.5 text-right">
                        {formatAmount(a.amount)} {base}
                      </td>
                      <td className="py-1.5 pl-3 text-right">
                        {a.status === "cancelled" && <Badge variant="muted">Cancelled</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>

      <div className="flex flex-col gap-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardContent className="flex flex-col gap-2 py-4">
            {entry.status === "submitted" && can("payments.cancel") && (
              <Button variant="outline" className="justify-start" onClick={() => setCancelOpen(true)}>
                <Ban /> Cancel payment
              </Button>
            )}
            {entry.status === "submitted" && can("payments.submit") && (
              <Button variant="outline" className="justify-start" loading={reconcile.isPending} onClick={() => reconcile.mutate()}>
                <Landmark /> {entry.reconciled_at ? "Unmark bank check" : "Mark as checked against bank"}
              </Button>
            )}
            {entry.status === "cancelled" && can("payments.create") && (
              <Button className="justify-start" loading={amend.isPending} onClick={() => amend.mutate()}>
                <CopyPlus /> Amend (enter corrected copy)
              </Button>
            )}
          </CardContent>
        </Card>
        {/* The ledger is for finance; employees reading their own payments don't get it. */}
        {seesLedger && entry.journal_entry_id && <JournalTable id={entry.journal_entry_id} title="Ledger entry" />}
        {seesLedger && entry.reversal_journal_entry_id && <JournalTable id={entry.reversal_journal_entry_id} title="Reversal" />}
      </div>

      <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel {entry.number}?</DialogTitle>
            <DialogDescription>
              A reversing entry is posted on the original date and the employee split is cancelled. To correct the payment, amend it
              afterwards.
            </DialogDescription>
          </DialogHeader>
          <FormField id="cancel_reason" label="Reason" required hint="Kept in the audit log.">
            <Textarea id="cancel_reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </FormField>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCancelOpen(false)}>
              Keep payment
            </Button>
            <Button variant="destructive" disabled={reason.trim().length < 3} loading={cancel.isPending} onClick={() => cancel.mutate()}>
              Cancel payment
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
