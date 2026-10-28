"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Undo2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { JournalLinesEditor, linesValid, newLine, toLineBody, type DraftLine } from "@/components/accounting/journal-editor";
import { DataTable } from "@/components/erp/data-table";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { useAccounts, useCompany } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { JournalEntry, Page } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const TYPE_LABEL: Record<string, string> = { manual: "Manual", payment: "Payment", opening: "Opening", reversal: "Reversal" };

function NewJournalDialog({ opening, onClose }: { opening: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const accounts = useAccounts();
  const base = useCompany().data?.base_currency ?? "USD";
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [memo, setMemo] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([newLine(), newLine()]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const foreign = (id: string | null) => {
    const cur = accounts.data?.find((a) => a.id === id)?.currency;
    return !!cur && cur !== base;
  };

  const post = useMutation({
    mutationFn: () => {
      const body = { posting_date: date, memo: memo || null, lines: lines.filter((l) => l.account_id).map((l) => toLineBody(l, foreign(l.account_id))) };
      return api.post<JournalEntry>(opening ? "/opening-balances" : "/journal-entries", body, { idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: (je) => {
      qc.invalidateQueries({ queryKey: ["journal-entries"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(`${je.number} posted`);
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
          <DialogTitle>{opening ? "Opening balances" : "New journal entry"}</DialogTitle>
          <DialogDescription>
            {opening
              ? "Enter each account's balance on the day before go-live. Any difference goes to Opening Balance Equity."
              : "For adjustments that aren't payments. Posted immediately and can only be undone by a reversal."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
          <FormField id="je_date" label={opening ? "Balances as of" : "Date"} error={errors.posting_date}>
            <Input id="je_date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </FormField>
          {!opening && (
            <FormField id="je_memo" label="Memo">
              <Textarea id="je_memo" className="min-h-9" value={memo} onChange={(e) => setMemo(e.target.value)} />
            </FormField>
          )}
        </div>
        <JournalLinesEditor lines={lines} onChange={setLines} allowUnbalanced={opening} errors={errors} />
        {errors.lines && <p role="alert" className="text-sm text-destructive">{errors.lines}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={post.isPending} disabled={!linesValid(lines.filter((l) => l.account_id || l.debit || l.credit))} onClick={() => post.mutate()}>
            Post entry
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function JournalDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const can = useCan();
  const je = useQuery({ queryKey: ["journal-entry", id], queryFn: () => api.get<JournalEntry>(`/journal-entries/${id}`) });
  const [reason, setReason] = useState("");
  const reverse = useMutation({
    mutationFn: () => api.post<JournalEntry>(`/journal-entries/${id}/reverse`, { reason }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["journal-entries"] });
      qc.invalidateQueries({ queryKey: ["journal-entry", id] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(`Reversed by ${r.number}`);
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not reverse"),
  });
  const e = je.data;
  const reversible = e && e.status === "posted" && e.entry_type !== "reversal" && !e.source_type && can("journals.post");

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {e?.number} {e && <Badge variant={e.status === "reversed" ? "muted" : "default"}>{e.status === "reversed" ? "Reversed" : TYPE_LABEL[e.entry_type]}</Badge>}
          </DialogTitle>
          {e && (
            <DialogDescription>
              {formatDate(e.posting_date)}
              {e.memo ? ` · ${e.memo}` : ""}
              {e.source_type === "payment_entry" && e.source_id && (
                <> · <Link className="text-primary hover:underline" href={`/accounting/payment-entries/${e.source_id}`}>{e.source_number}</Link></>
              )}
            </DialogDescription>
          )}
        </DialogHeader>
        {e && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-1.5 text-left font-medium">Account</th>
                  <th className="py-1.5 text-left font-medium">Tags</th>
                  <th className="py-1.5 text-right font-medium">Debit</th>
                  <th className="py-1.5 text-right font-medium">Credit</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {e.lines.map((l) => (
                  <tr key={l.line_no} className="border-b last:border-0">
                    <td className="py-1.5"><span className="font-mono text-xs text-muted-foreground">{l.account_code}</span> {l.account_name}</td>
                    <td className="py-1.5 text-xs text-muted-foreground">{[l.party_name, l.project_name, l.employee_name].filter(Boolean).join(" · ")}</td>
                    <td className="py-1.5 text-right">{Number(l.debit) ? formatAmount(l.debit) : ""}</td>
                    <td className="py-1.5 text-right">{Number(l.credit) ? formatAmount(l.credit) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {reversible && (
          <div className="flex flex-col gap-2 rounded-md border p-3">
            <FormField id="rev_reason" label="Reverse this entry" hint="Posts a mirror entry on the same date. Give a reason for the audit log.">
              <Input id="rev_reason" placeholder="Reason" value={reason} onChange={(ev) => setReason(ev.target.value)} />
            </FormField>
            <Button variant="outline" className="self-end" disabled={reason.trim().length < 3} loading={reverse.isPending} onClick={() => reverse.mutate()}>
              <Undo2 /> Reverse
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function JournalEntriesPage() {
  const can = useCan();
  const [page, setPage] = useState(1);
  const [type, setType] = useState("");
  const [dialog, setDialog] = useState<"manual" | "opening" | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const entries = useQuery({
    queryKey: ["journal-entries", page, type],
    queryFn: () => api.get<Page<JournalEntry>>("/journal-entries", { page, page_size: 25, entry_type: type }),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<JournalEntry, unknown>[]>(
    () => [
      { accessorKey: "posting_date", header: "Date", cell: ({ row }) => formatDate(row.original.posting_date) },
      {
        accessorKey: "number",
        header: "Number",
        cell: ({ row }) => (
          <button type="button" className="font-mono text-xs text-primary hover:underline" onClick={() => setDetail(row.original.id)}>
            {row.original.number}
          </button>
        ),
      },
      {
        accessorKey: "entry_type",
        header: "Type",
        cell: ({ row }) => (
          <span className="flex gap-1">
            <Badge variant="muted">{TYPE_LABEL[row.original.entry_type]}</Badge>
            {row.original.status === "reversed" && <Badge variant="warning">Reversed</Badge>}
          </span>
        ),
      },
      {
        id: "memo",
        header: "Source / memo",
        enableSorting: false,
        cell: ({ row }) => <span className="line-clamp-1 text-muted-foreground">{row.original.source_number ?? row.original.memo ?? ""}</span>,
      },
      {
        id: "total",
        header: () => <span className="block text-right">Total</span>,
        accessorFn: (e) => Number(e.total),
        cell: ({ row }) => <span className="tabular block text-right">{formatAmount(row.original.total)}</span>,
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Journal entries"
        description="Everything posted to the ledger. Payments create their entries automatically; use manual entries for adjustments."
        actions={can("journals.post") && (
          <>
            <Button variant="outline" onClick={() => setDialog("opening")}>Opening balances</Button>
            <Button onClick={() => setDialog("manual")}><Plus /> New entry</Button>
          </>
        )}
      />
      <Card>
        <div className="border-b p-3">
          <Select aria-label="Type" className="sm:w-48" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">All types</option>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </div>
        <DataTable columns={columns} data={entries.data?.items} isLoading={entries.isLoading} error={entries.error}
          getRowId={(e) => e.id} pagination={entries.data && { page, pageSize: 25, total: entries.data.total, onPageChange: setPage }} />
      </Card>
      {dialog && <NewJournalDialog opening={dialog === "opening"} onClose={() => setDialog(null)} />}
      {detail && <JournalDetail id={detail} onClose={() => setDetail(null)} />}
    </>
  );
}
