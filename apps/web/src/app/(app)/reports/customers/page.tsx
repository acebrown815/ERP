"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Delta, num, PeriodChart, SERIES, StatTile } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { DrillAmount, MonthsSelect, shortLabel } from "@/components/reports/shared";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import type { CustomerAnalysis } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const STATUS = {
  new: { label: "New", variant: "success" },
  active: { label: "Active", variant: "default" },
  lapsing: { label: "Going quiet", variant: "warning" },
  lapsed: { label: "Lapsed", variant: "destructive" },
} as const;

/** Revenue per period split into the top three customers and everyone else (four colour slots, fixed order). */
function chartOf(r: CustomerAnalysis) {
  const top = r.rows.filter((x) => num(x.total) > 0).slice(0, 3);
  const bars = top.map((x, i) => ({ key: `c${i}`, label: x.party_name, color: SERIES[i]!, stack: "rev" }));
  bars.push({ key: "other", label: "Other customers", color: SERIES[3], stack: "rev" });
  const data = r.periods.map((p, i) => {
    const row: Record<string, string | number> = { label: shortLabel(p.label) };
    let used = 0;
    top.forEach((x, k) => {
      row[`c${k}`] = num(x.by_period[i]);
      used += num(x.by_period[i]);
    });
    row.other = Math.max(0, num(r.by_period[i]!.revenue) - used);
    return row;
  });
  return { bars, data };
}

export default function CustomersPage() {
  const [periods, setPeriods] = useState(12);
  const q = useQuery({
    queryKey: ["report-customers", periods],
    queryFn: () => api.get<CustomerAnalysis>("/reports/customers", { periods }),
    placeholderData: keepPreviousData,
  });
  const r = q.data;
  const base = r?.base_currency ?? "";
  const done = r ? r.by_period.filter((_, i) => !r.periods[i]!.in_progress) : [];
  const last = done.at(-1);
  const before = done.at(-2);
  const lastLabel = r ? r.periods.filter((p) => !p.in_progress).at(-1)?.label : undefined;
  const quiet = r?.rows.filter((x) => x.status === "lapsing" || x.status === "lapsed") ?? [];
  const top1 = r?.concentration.top1_pct ? Number(r.concentration.top1_pct) : 0;

  return (
    <>
      <PageHeader
        title="Customer analysis"
        description="Who pays you, how much, how regularly, and how dependent you are on your biggest customers. Months are salary periods."
        actions={
          <>
            <MonthsSelect value={periods} onChange={setPeriods} />
            <ExportMenu path="/reports/customers" params={{ periods: String(periods) }} />
          </>
        }
      />
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !r ? <TableSkeleton /> : r.rows.length === 0 ? (
        <EmptyState title="No customer payments yet" />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label={`Received, last ${r.periods.length} months`} value={formatAmount(r.total)} unit={base} hint={`From ${r.rows.filter((x) => num(x.total) > 0).length} customers`} />
            <StatTile
              label={lastLabel ? `Paying customers · ${lastLabel}` : "Paying customers"}
              value={last ? String(last.paying_customers) : "—"}
              delta={last && <Delta current={last.paying_customers} previous={before?.paying_customers ?? null} />}
              hint={last ? `${last.new_customers} new` : undefined}
            />
            <StatTile
              label="Biggest customer's share"
              value={r.concentration.top1_pct ? `${r.concentration.top1_pct}%` : "—"}
              tone={top1 > 50 ? "bad" : undefined}
              hint={`Top 3: ${r.concentration.top3_pct ?? "—"}% · Top 5: ${r.concentration.top5_pct ?? "—"}%`}
            >
              {top1 > 50 && <p className="mt-1 text-xs text-destructive">More than half your revenue depends on one customer.</p>}
            </StatTile>
            <StatTile
              label="Going quiet"
              value={String(quiet.length)}
              tone={quiet.length ? "bad" : undefined}
              hint={`No payment for ${r.lapsing_days}+ days (lapsed after ${r.lapsed_days})`}
            />
          </div>

          <Card className="mb-6">
            <CardHeader><CardTitle>Revenue by customer</CardTitle><CardDescription>Your three biggest customers in this range, and everyone else.</CardDescription></CardHeader>
            <CardContent>
              {(() => {
                const { bars, data } = chartOf(r);
                return <PeriodChart label="Revenue per month by customer" data={data} bars={bars} unit={base} />;
              })()}
            </CardContent>
          </Card>

          {quiet.length > 0 && (
            <Card className="mb-6">
              <CardHeader><CardTitle>Customers going quiet</CardTitle><CardDescription>Paid within the last year, but not in the last {r.lapsing_days} days.</CardDescription></CardHeader>
              <CardContent>
                <ul className="flex flex-col divide-y text-sm">
                  {quiet.sort((a, b) => (b.days_since_last ?? 0) - (a.days_since_last ?? 0)).map((x) => (
                    <li key={x.party_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                      <Link href={`/parties/${x.party_id}`} className="font-medium hover:underline">{x.party_name}</Link>
                      <span className="flex items-center gap-3 text-muted-foreground">
                        Last paid {formatDate(x.last_payment)} · {x.days_since_last} days ago
                        <Badge variant={STATUS[x.status as keyof typeof STATUS]?.variant ?? "muted"}>{STATUS[x.status as keyof typeof STATUS]?.label ?? x.status}</Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <Card className="overflow-x-auto">
            <CardHeader><CardTitle>Customer × month</CardTitle><CardDescription>Click an amount to see the payments.</CardDescription></CardHeader>
            <Table>
              <THead>
                <TR>
                  <TH className="sticky left-0 bg-card">Customer</TH>
                  {r.periods.map((p) => <TH key={p.id} className="whitespace-nowrap text-right">{shortLabel(p.label)}</TH>)}
                  <TH className="text-right">Total</TH>
                  <TH className="text-right">Share</TH>
                  <TH>Last paid</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {r.rows.map((x) => (
                  <TR key={x.party_id}>
                    <TD className="sticky left-0 bg-card"><Link href={`/parties/${x.party_id}`} className="font-medium hover:underline">{x.party_name}</Link></TD>
                    {r.periods.map((p, i) => (
                      <TD key={p.id} className="tabular text-right">
                        <DrillAmount value={x.by_period[i]!} drill={{ party_id: x.party_id, direction: "receive", from: p.start_date, to: p.end_date }} />
                      </TD>
                    ))}
                    <TD className="tabular text-right font-medium">{formatAmount(x.total)}</TD>
                    <TD className="tabular text-right text-muted-foreground">{x.share_pct ? `${x.share_pct}%` : "—"}</TD>
                    <TD className="whitespace-nowrap text-sm">{formatDate(x.last_payment)}</TD>
                    <TD><Badge variant={STATUS[x.status as keyof typeof STATUS]?.variant ?? "muted"}>{STATUS[x.status as keyof typeof STATUS]?.label ?? x.status}</Badge></TD>
                  </TR>
                ))}
                <TR className="font-medium">
                  <TD className="sticky left-0 bg-card">Total ({base})</TD>
                  {r.by_period.map((b, i) => <TD key={i} className="tabular text-right">{formatAmount(b.revenue)}</TD>)}
                  <TD className="tabular text-right">{formatAmount(r.total)}</TD>
                  <TD colSpan={3} />
                </TR>
                <TR className="text-muted-foreground">
                  <TD className="sticky left-0 bg-card text-sm">Paying / new customers</TD>
                  {r.by_period.map((b, i) => <TD key={i} className="tabular text-right text-sm">{b.paying_customers} / {b.new_customers}</TD>)}
                  <TD colSpan={4} />
                </TR>
              </TBody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}
