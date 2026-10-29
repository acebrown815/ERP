"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable } from "@/components/erp/data-table";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { Combobox } from "@/components/erp/combobox";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Input, Textarea } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useAccounts, usePaymentAccounts } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { PaymentAccount } from "@/lib/types";

const KIND: Record<string, string> = { bank: "Bank", cash: "Cash", crypto_wallet: "Crypto wallet", credit_card: "Credit card" };
const MONEY = Object.keys(KIND);

function PaymentAccountDialog({ pa, onClose }: { pa: PaymentAccount | null; onClose: () => void }) {
  const qc = useQueryClient();
  const accounts = useAccounts();
  const used = new Set((usePaymentAccounts(true).data ?? []).map((p) => p.account_id));
  const [name, setName] = useState(pa?.name ?? "");
  const [accountId, setAccountId] = useState<string | null>(pa?.account_id ?? null);
  const [details, setDetails] = useState(
    Object.entries(pa?.details ?? {}).map(([k, v]) => `${k}: ${v}`).join("\n"),
  );
  const [notes, setNotes] = useState(pa?.notes ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const parsed = Object.fromEntries(
    details.split("\n").map((l) => l.split(":")).filter((p) => p.length >= 2 && p[0]!.trim())
      .map(([k, ...v]) => [k!.trim(), v.join(":").trim()]),
  );

  const save = useMutation({
    mutationFn: () =>
      pa
        ? api.patch<PaymentAccount>(`/payment-accounts/${pa.id}`, { version: pa.version, name, details: parsed, notes: notes || null })
        : api.post<PaymentAccount>("/payment-accounts", { name, account_id: accountId, details: parsed, notes: notes || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payment-accounts"] });
      toast.success("Saved");
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        if (!err.errors.length) toast.error(err.message);
      }
    },
  });

  const options = (accounts.data ?? [])
    .filter((a) => !a.is_group && a.is_active && MONEY.includes(a.account_type) && (!used.has(a.id) || a.id === pa?.account_id))
    .map((a) => ({ value: a.id, label: `${a.code} · ${a.name}`, hint: `${KIND[a.account_type]} · ${a.currency}` }));

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{pa ? `Edit ${pa.name}` : "New payment account"}</DialogTitle>
          <DialogDescription>A bank account, cash box, card or wallet. It is backed by one ledger account, which sets its currency.</DialogDescription>
        </DialogHeader>
        <FormField id="pa_name" label="Name" required error={errors.name}><Input id="pa_name" value={name} onChange={(e) => setName(e.target.value)} /></FormField>
        <FormField id="pa_account" label="Ledger account" required error={errors.account_id}
          hint={pa ? "Can't be changed once created." : "Only bank, cash, crypto wallet and credit card accounts. Add one in the Chart of Accounts first if needed."}>
          <Combobox id="pa_account" value={accountId} onChange={setAccountId} options={options} disabled={!!pa} />
        </FormField>
        <FormField id="pa_details" label="Details" hint="One per line, e.g. “bank: Chase” or “iban: DE89…”. Shown masked to people who don't manage accounts.">
          <Textarea id="pa_details" className="font-mono text-xs" value={details} onChange={(e) => setDetails(e.target.value)} />
        </FormField>
        <FormField id="pa_notes" label="Notes"><Input id="pa_notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></FormField>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} disabled={!name.trim() || !accountId} onClick={() => save.mutate()}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function PaymentAccountsPage() {
  const can = useCan();
  const qc = useQueryClient();
  const manage = can("payment_accounts.manage");
  const [showInactive, setShowInactive] = useState(false);
  const accounts = usePaymentAccounts(showInactive);
  const [dialog, setDialog] = useState<{ pa: PaymentAccount | null } | null>(null);
  const toggle = useMutation({
    mutationFn: (pa: PaymentAccount) => api.patch<PaymentAccount>(`/payment-accounts/${pa.id}`, { version: pa.version, is_active: !pa.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payment-accounts"] }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update"),
  });
  const columns = useMemo<ColumnDef<PaymentAccount, unknown>[]>(
    () => [
      { accessorKey: "name", header: "Name", cell: ({ row }) => (
        <Link href={`/accounting/payment-entries?payment_account_id=${row.original.id}`} className="font-medium hover:underline" title="See its payments">{row.original.name}</Link>
      ) },
      { accessorKey: "kind", header: "Kind", cell: ({ row }) => KIND[row.original.kind] ?? row.original.kind },
      { accessorKey: "currency", header: "Currency" },
      { id: "ledger", header: "Ledger account", cell: ({ row }) => <span><span className="font-mono text-xs text-muted-foreground">{row.original.account_code}</span> {row.original.account_name}</span> },
      { id: "details", header: "Details", enableSorting: false, cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">{Object.entries(row.original.details).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}</span>
      ) },
      { accessorKey: "is_active", header: "Status", cell: ({ row }) => (row.original.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="muted">Inactive</Badge>) },
      { id: "actions", header: "", enableSorting: false, cell: ({ row }) => manage && (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="sm" onClick={() => setDialog({ pa: row.original })}>Edit</Button>
          <Button variant="ghost" size="sm" onClick={() => toggle.mutate(row.original)}>{row.original.is_active ? "Deactivate" : "Activate"}</Button>
        </div>
      ) },
    ],
    [manage, toggle],
  );
  return (
    <>
      <PageHeader title="Payment accounts" description="Where money is received and paid from. Payment methods (bank transfer, card…) are separate and set per payment."
        actions={manage && <Button onClick={() => setDialog({ pa: null })}><Plus /> New payment account</Button>} />
      <Card>
        <div className="flex justify-end border-b px-4 py-2">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Checkbox checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show inactive
          </label>
        </div>
        <DataTable columns={columns} data={accounts.data} isLoading={accounts.isLoading} error={accounts.error} getRowId={(p) => p.id} />
      </Card>
      {dialog && <PaymentAccountDialog pa={dialog.pa} onClose={() => setDialog(null)} />}
    </>
  );
}
