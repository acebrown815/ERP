"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { DateRange, usePreviousRange, yearRange, type Range } from "@/components/accounting/report-controls";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { ChangeText, DrillAmount } from "@/components/reports/shared";
import { Checkbox } from "@/components/ui/input";
import { Card, CardContent, Label } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, subtract } from "@/lib/money";
import type { PartyReport } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

export default function PartyPaymentsPage() {
  const [range, setRange] = useState<Range>(yearRange());
  const [direction, setDirection] = useState<"receive" | "pay">("receive");
  const q = useQuery({
    queryKey: ["report-party-payments", direction, range],
    queryFn: () => api.get<PartyReport>("/reports/party-payments", { direction, from: range.from, to: range.to }),
    placeholderData: keepPreviousData,
  });
  const r = q.data;
  const [compare, setCompare] = useState(true);
  const prev = usePreviousRange(range);
  const pq = useQuery({
    queryKey: ["report-party-payments", direction, { from: prev.from, to: prev.to }],
    queryFn: () => api.get<PartyReport>("/reports/party-payments", { direction, from: prev.from, to: prev.to }),
    enabled: compare,
  });
  const before = new Map((pq.data?.rows ?? []).map((x) => [x.party_id ?? "", x.total]));
  const showPrev = compare && !!pq.data;
  const change = (now: string, then: string | undefined) => subtract(now, then ?? "0");
  return (
    <>
      <PageHeader
        title={direction === "receive" ? "Customer payments" : "Supplier payments"}
        description="Submitted payments per party, in the base currency, biggest first."
        actions={<ExportMenu path="/reports/party-payments" params={{ direction, from: range.from, to: range.to }} />}
      />
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <div className="flex gap-1 rounded-md border p-0.5 text-sm" role="radiogroup" aria-label="Direction">
            {(["receive", "pay"] as const).map((d) => (
              <button key={d} type="button" role="radio" aria-checked={direction === d} onClick={() => setDirection(d)}
                className={cn("rounded px-3 py-1", direction === d ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground")}>
                {d === "receive" ? "Customers (received)" : "Suppliers (paid)"}
              </button>
            ))}
          </div>
          <DateRange {...range} onChange={setRange} />
          <div className="flex items-center gap-2">
            <Checkbox id="cmp" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
            <Label htmlFor="cmp" className="font-normal">Compare with {prev.label}</Label>
          </div>
        </CardContent>
      </Card>
      <Card>
        {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
          <EmptyState title="No payments in this range" />
        ) : (
          <Table>
            <THead><TR><TH>Party</TH><TH className="text-right">Payments</TH><TH className="text-right">Last</TH><TH className="w-1/4">Share</TH><TH className="text-right">Total ({r.base_currency})</TH>{showPrev && <><TH className="text-right">{prev.label}</TH><TH className="text-right">Change</TH></>}</TR></THead>
            <TBody>
              {r.rows.map((row, i) => (
                <TR key={row.party_id ?? i}>
                  <TD>{row.party_id ? <Link className="font-medium hover:underline" href={`/parties/${row.party_id}`}>{row.party_name}</Link> : <span className="text-muted-foreground">{row.party_name}</span>}</TD>
                  <TD className="tabular text-right">{row.payments}</TD>
                  <TD className="text-right text-sm">{formatDate(row.last_payment)}</TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Number(row.share_pct)}%` }} /></div>
                      <span className="tabular w-12 text-right text-xs text-muted-foreground">{row.share_pct}%</span>
                    </div>
                  </TD>
                  <TD className="tabular text-right">
                    <DrillAmount value={row.total} drill={{ party_id: row.party_id, direction, from: range.from, to: range.to }} />
                  </TD>
                  {showPrev && (
                    <>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(before.get(row.party_id ?? "") ?? "0")}</TD>
                      <TD className="whitespace-nowrap text-right"><ChangeText value={change(row.total, before.get(row.party_id ?? ""))} goodWhenUp={direction === "receive"} /></TD>
                    </>
                  )}
                </TR>
              ))}
              <TR className="font-medium"><TD>Total</TD><TD className="tabular text-right">{r.rows.reduce((n, x) => n + x.payments, 0)}</TD><TD /><TD /><TD className="tabular text-right">{formatAmount(r.total)}</TD>{showPrev && <><TD className="tabular text-right">{formatAmount(pq.data!.total)}</TD><TD className="whitespace-nowrap text-right"><ChangeText value={change(r.total, pq.data!.total)} goodWhenUp={direction === "receive"} /></TD></>}</TR>
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
