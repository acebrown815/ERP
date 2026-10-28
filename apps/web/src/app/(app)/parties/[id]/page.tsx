"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Pencil } from "lucide-react";
import Link from "next/link";
import { use, useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState } from "@/components/erp/states";
import { KIND_LABEL, PartyDialog, type PartyKind } from "@/components/parties/party-dialog";
import { StatusBadge } from "@/components/payments/entry-view";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { formatAmount, formatShort } from "@/lib/money";
import { currencyPrecision, useCompany, useCurrencies, useParty } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { Page, Party, PaymentEntry } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function PartyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const can = useCan();
  const qc = useQueryClient();
  const base = useCompany().data?.base_currency ?? "USD";
  const currencies = useCurrencies();
  const party = useParty(id);
  const canSeePayments = can("payments.create") || can("reports.financial");
  const summary = useQuery({
    queryKey: ["party-summary", id],
    queryFn: () => api.get<{ received: string; paid: string; count: string }>("/payment-entries/party-summary", { party_id: id }),
    enabled: canSeePayments,
  });
  const payments = useQuery({
    queryKey: ["payment-entries", "party", id],
    queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { party_id: id, page_size: 50 }),
    enabled: canSeePayments,
  });
  const [editing, setEditing] = useState(false);
  const toggle = useMutation({
    mutationFn: (p: Party) => api.patch<Party>(`/parties/${p.id}`, { version: p.version, is_active: !p.is_active }),
    onSuccess: (p) => {
      qc.setQueryData(["party", p.id], p);
      qc.invalidateQueries({ queryKey: ["parties"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update"),
  });
  const columns = useMemo<ColumnDef<PaymentEntry, unknown>[]>(
    () => [
      { accessorKey: "posting_date", header: "Date", cell: ({ row }) => formatDate(row.original.posting_date) },
      { accessorKey: "number", header: "Number", cell: ({ row }) => <Link className="font-mono text-xs text-primary hover:underline" href={`/accounting/payment-entries/${row.original.id}`}>{row.original.number}</Link> },
      { id: "project", header: "Project", cell: ({ row }) => row.original.project_name ?? "—" },
      { id: "amount", header: () => <span className="block text-right">Amount</span>, cell: ({ row }) => (
        <span className="tabular block text-right">{row.original.direction === "pay" ? "−" : ""}{formatShort(row.original.amount, currencyPrecision(currencies.data, row.original.currency))} {row.original.currency}</span>
      ) },
      { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    ],
    [currencies.data],
  );

  if (party.isError) return <ErrorState error={party.error} onRetry={() => party.refetch()} />;
  if (!party.data) return <Skeleton className="h-72 w-full" />;
  const p = party.data;
  const kind = p.kind as PartyKind;
  const back = { customer: "/parties/customers", supplier: "/parties/suppliers", other: "/parties/other" }[kind];

  return (
    <>
      <PageHeader
        title={p.name}
        description={<span className="flex items-center gap-2"><Badge variant="muted">{KIND_LABEL[kind].one}</Badge><span className="font-mono text-xs">{p.number}</span>{!p.is_active && <Badge variant="warning">Inactive</Badge>}<Link href={back} className="text-primary hover:underline">All {KIND_LABEL[kind].many.toLowerCase()}</Link></span>}
        actions={can("parties.manage") && (
          <>
            <Button variant="outline" loading={toggle.isPending} onClick={() => toggle.mutate(p)}>{p.is_active ? "Deactivate" : "Activate"}</Button>
            <Button onClick={() => setEditing(true)}><Pencil /> Edit</Button>
          </>
        )}
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent>
            <dl className="flex flex-col gap-2 text-sm">
              {[["Contact", p.contact_name], ["Email", p.email], ["Phone", p.phone], ["Website", p.website], ["Currency", p.default_currency], ["Notes", p.notes]]
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[6rem_1fr] gap-2"><dt className="text-muted-foreground">{k}</dt><dd className="break-words">{v}</dd></div>
                ))}
            </dl>
          </CardContent>
        </Card>
        {canSeePayments && (
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>Totals ({base})</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-3 gap-4">
              {[["Received", summary.data?.received], ["Paid", summary.data?.paid], ["Payments", summary.data?.count]].map(([k, v]) => (
                <div key={k}>
                  <p className="text-sm text-muted-foreground">{k}</p>
                  <p className="tabular text-2xl font-semibold">{k === "Payments" ? Number(v ?? 0) : formatAmount(v ?? "0")}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
      {canSeePayments && (
        <Card className="mt-6">
          <CardHeader><CardTitle>Payments</CardTitle></CardHeader>
          <DataTable columns={columns} data={payments.data?.items} isLoading={payments.isLoading} error={payments.error} getRowId={(e) => e.id} />
        </Card>
      )}
      {editing && <PartyDialog kind={kind} party={p} onClose={() => setEditing(false)} />}
    </>
  );
}
