"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { CsvButton, DateRange, usePeriodRanges, type Range } from "@/components/accounting/report-controls";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { AccountPicker, PartyPicker, ProjectPicker } from "@/components/erp/pickers";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Checkbox } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { useCompany } from "@/lib/queries";
import type { Ledger } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function GeneralLedgerPage() {
  const base = useCompany().data?.base_currency ?? "USD";
  // Defaults to the current salary period (the company's "month").
  const periods = usePeriodRanges();
  const [chosen, setRange] = useState<Range | null>(null);
  const range = chosen ?? { from: periods.current.from, to: periods.current.to };
  const [accountId, setAccountId] = useState<string | null>(null);
  const [partyId, setPartyId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [includeReversed, setIncludeReversed] = useState(false);
  const params = { from: range.from, to: range.to, account_id: accountId, party_id: partyId, project_id: projectId,
    include_reversed: includeReversed ? "true" : undefined };
  const ledger = useQuery({
    queryKey: ["general-ledger", params],
    queryFn: () => api.get<Ledger>("/reports/general-ledger", params),
    placeholderData: keepPreviousData,
    enabled: !!range.from && !!range.to && (!!chosen || !periods.loading),
  });
  const l = ledger.data;

  return (
    <>
      <PageHeader title="General ledger" description={`Every posted line, in ${base}. Pick an account to see its running balance.`}
        actions={<CsvButton path="/reports/general-ledger" params={params} />} />
      <Card>
        <div className="grid gap-3 border-b p-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="md:col-span-2"><DateRange {...range} onChange={setRange} /></div>
          <FormField id="gl_account" label="Account"><AccountPicker id="gl_account" leafOnly={false} value={accountId} onChange={setAccountId} placeholder="All accounts" /></FormField>
          <FormField id="gl_party" label="Party"><PartyPicker id="gl_party" value={partyId} onChange={setPartyId} placeholder="All parties" /></FormField>
          <FormField id="gl_project" label="Project"><ProjectPicker id="gl_project" value={projectId} onChange={setProjectId} placeholder="All projects" /></FormField>
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-muted-foreground">
            <Checkbox checked={includeReversed} onChange={(e) => setIncludeReversed(e.target.checked)} /> Show cancelled entries and their reversals
          </label>
        </div>
        {ledger.isError ? <ErrorState error={ledger.error} onRetry={() => ledger.refetch()} /> : !l ? <TableSkeleton /> : l.rows.length === 0 ? (
          <EmptyState title="No postings in this range" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="h-10 px-3 text-left font-medium">Date</th>
                  <th className="h-10 px-3 text-left font-medium">Entry</th>
                  <th className="h-10 px-3 text-left font-medium">Account</th>
                  <th className="h-10 px-3 text-left font-medium">Details</th>
                  <th className="h-10 px-3 text-right font-medium">Debit</th>
                  <th className="h-10 px-3 text-right font-medium">Credit</th>
                  {l.opening_balance !== null && <th className="h-10 px-3 text-right font-medium">Balance</th>}
                </tr>
              </thead>
              <tbody className="tabular">
                {l.opening_balance !== null && (
                  <tr className="border-b bg-muted/30 text-muted-foreground">
                    <td className="px-3 py-2" colSpan={6}>Opening balance</td>
                    <td className="px-3 py-2 text-right">{formatAmount(l.opening_balance)}</td>
                  </tr>
                )}
                {l.rows.map((r) => (
                  <tr key={r.line_id} className={`border-b hover:bg-muted/40 ${r.status === "reversed" || r.entry_type === "reversal" ? "text-muted-foreground line-through" : ""}`}>
                    <td className="whitespace-nowrap px-3 py-2">{formatDate(r.posting_date)}</td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {r.source_type === "payment_entry" && r.source_id ? (
                        <Link className="text-primary hover:underline" href={`/accounting/payment-entries/${r.source_id}`}>{r.source_number}</Link>
                      ) : r.number}
                    </td>
                    <td className="px-3 py-2"><span className="font-mono text-xs text-muted-foreground">{r.account_code}</span> {r.account_name}</td>
                    <td className="max-w-72 px-3 py-2 text-muted-foreground">
                      <span className="line-clamp-1">{[r.party_name, r.project_name, r.description ?? r.memo].filter(Boolean).join(" · ")}</span>
                    </td>
                    <td className="px-3 py-2 text-right">{Number(r.debit) ? formatAmount(r.debit) : ""}</td>
                    <td className="px-3 py-2 text-right">{Number(r.credit) ? formatAmount(r.credit) : ""}</td>
                    {l.opening_balance !== null && <td className="px-3 py-2 text-right">{formatAmount(r.balance)}</td>}
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t-2 font-medium">
                <tr>
                  <td className="px-3 py-2" colSpan={4}>Totals{l.truncated ? " (first 2,000 lines; narrow the filters)" : ""}</td>
                  <td className="tabular px-3 py-2 text-right">{formatAmount(l.total_debit)}</td>
                  <td className="tabular px-3 py-2 text-right">{formatAmount(l.total_credit)}</td>
                  {l.opening_balance !== null && <td className="tabular px-3 py-2 text-right">{formatAmount(l.closing_balance)}</td>}
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
