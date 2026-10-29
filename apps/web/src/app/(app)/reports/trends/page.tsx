"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { num, PeriodChart, SERIES } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { ChangeText, DrillAmount, MonthsSelect, shortLabel } from "@/components/reports/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import type { TrendRow, Trends } from "@/lib/types";
import { cn } from "@/lib/utils";

type Kind = "expense" | "income";

const rowName = (r: TrendRow) => r.category_name ?? r.account_name ?? "?";

function chartOf(t: Trends) {
  const top = t.categories.slice(0, 3);
  const bars = top.map((r, i) => ({ key: `k${i}`, label: rowName(r), color: SERIES[i]!, stack: "s" }));
  if (t.categories.length > 3) bars.push({ key: "other", label: "Everything else", color: SERIES[3], stack: "s" });
  const data = t.periods.map((p, i) => {
    const row: Record<string, string | number> = { label: shortLabel(p.label) };
    let used = 0;
    top.forEach((r, k) => {
      row[`k${k}`] = num(r.by_period[i]);
      used += num(r.by_period[i]);
    });
    if (t.categories.length > 3) row.other = num(t.totals[i]) - used;
    return row;
  });
  return { bars, data };
}

function Movers({ t, kind }: { t: Trends; kind: Kind }) {
  const rows = t.categories.filter((r) => r.change && num(r.change) !== 0);
  const up = [...rows].sort((a, b) => num(b.change) - num(a.change)).filter((r) => num(r.change) > 0).slice(0, 5);
  const down = [...rows].sort((a, b) => num(a.change) - num(b.change)).filter((r) => num(r.change) < 0).slice(0, 5);
  const [older, newer] = t.compare.map((i) => t.periods[i]!.label);
  const goodWhenUp = kind === "income";
  const list = (items: TrendRow[], dir: "up" | "down") => (
    <ul className="flex flex-col divide-y text-sm">
      {items.length === 0 && <li className="py-2 text-muted-foreground">None</li>}
      {items.map((r) => (
        <li key={r.key} className="flex items-center justify-between gap-3 py-2">
          <span className="flex min-w-0 items-center gap-2">
            {dir === "up" ? <ArrowUpRight className="size-4 shrink-0 text-muted-foreground" aria-hidden /> : <ArrowDownRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
            <span className="truncate">{rowName(r)}</span>
          </span>
          <ChangeText value={r.change} pct={r.change_pct} goodWhenUp={goodWhenUp} />
        </li>
      ))}
    </ul>
  );
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Biggest changes</CardTitle>
        <CardDescription>{older && newer ? `${newer} compared with ${older} (the last two full months).` : "Needs two full months."}</CardDescription>
      </CardHeader>
      {older && newer && (
        <CardContent className="grid gap-6 md:grid-cols-2">
          <div><p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Went up</p>{list(up, "up")}</div>
          <div><p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Went down</p>{list(down, "down")}</div>
        </CardContent>
      )}
    </Card>
  );
}

function Matrix({ t, rows, kind, by }: { t: Trends; rows: TrendRow[]; kind: Kind; by: "category" | "party" }) {
  const direction = kind === "income" ? "receive" : "pay";
  return (
    <Table>
      <THead>
        <TR>
          <TH className="sticky left-0 bg-card">{by === "category" ? "Account / category" : kind === "income" ? "Customer" : "Supplier / payee"}</TH>
          {t.periods.map((p) => <TH key={p.id} className="whitespace-nowrap text-right">{shortLabel(p.label)}</TH>)}
          <TH className="text-right">Total</TH>
          <TH className="text-right" title="Last full month vs the one before">Change</TH>
        </TR>
      </THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.key}>
            <TD className="sticky left-0 bg-card">
              {by === "category" ? (
                <>
                  <span className="font-medium">{rowName(r)}</span>
                  {r.category_name && <span className="block text-xs text-muted-foreground">{r.account_code} {r.account_name}</span>}
                </>
              ) : r.party_id ? <Link href={`/parties/${r.party_id}`} className="font-medium hover:underline">{r.party_name}</Link> : <span className="text-muted-foreground">{r.party_name}</span>}
            </TD>
            {t.periods.map((p, i) => (
              <TD key={p.id} className="tabular text-right">
                {by === "party" && r.party_id ? (
                  <DrillAmount value={r.by_period[i]!} drill={{ party_id: r.party_id, direction, from: p.start_date, to: p.end_date }} />
                ) : (
                  <span className={cn(num(r.by_period[i]) === 0 && "text-muted-foreground")}>{formatAmount(r.by_period[i])}</span>
                )}
              </TD>
            ))}
            <TD className="tabular text-right font-medium">{formatAmount(r.total)}</TD>
            <TD className="whitespace-nowrap text-right"><ChangeText value={r.change} pct={r.change_pct} goodWhenUp={kind === "income"} /></TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export default function TrendsPage() {
  const [kind, setKind] = useState<Kind>("expense");
  const [periods, setPeriods] = useState(6);
  const q = useQuery({
    queryKey: ["report-trends", kind, periods],
    queryFn: () => api.get<Trends>("/reports/trends", { kind, periods }),
    placeholderData: keepPreviousData,
  });
  const t = q.data;
  const base = t?.base_currency ?? "";
  return (
    <>
      <PageHeader
        title={kind === "expense" ? "Expense trends" : "Income trends"}
        description="Month by month per account and category, and per supplier or customer, with what changed most. Months are salary periods."
        actions={
          <>
            <MonthsSelect value={periods} onChange={setPeriods} options={[3, 6, 12]} />
            <ExportMenu path="/reports/trends" params={{ kind, periods: String(periods) }} />
          </>
        }
      />
      <div className="mb-4 flex w-fit gap-1 rounded-md border p-0.5 text-sm" role="radiogroup" aria-label="Show">
        {(["expense", "income"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
            className={cn("rounded px-3 py-1", kind === k ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground")}>
            {k === "expense" ? "Expenses" : "Income"}
          </button>
        ))}
      </div>
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !t ? <TableSkeleton /> : t.categories.length === 0 ? (
        <EmptyState title={kind === "expense" ? "No expenses in these months" : "No income in these months"} />
      ) : (
        <>
          <Card className="mb-6">
            <CardHeader><CardTitle>{kind === "expense" ? "Where the money goes" : "Where the money comes from"}</CardTitle><CardDescription>The three biggest categories in this range, and everything else.</CardDescription></CardHeader>
            <CardContent>
              {(() => {
                const { bars, data } = chartOf(t);
                return <PeriodChart label={`${kind === "expense" ? "Expenses" : "Income"} per month by category`} data={data} bars={bars} unit={base} />;
              })()}
            </CardContent>
          </Card>
          <Movers t={t} kind={kind} />
          <Card className="mb-6 overflow-x-auto">
            <CardHeader><CardTitle>By account and category</CardTitle></CardHeader>
            <Matrix t={t} rows={t.categories} kind={kind} by="category" />
          </Card>
          {t.parties.length > 0 && (
            <Card className="overflow-x-auto">
              <CardHeader><CardTitle>{kind === "expense" ? "By supplier" : "By customer"}</CardTitle><CardDescription>Payments made or received; click an amount to see them.</CardDescription></CardHeader>
              <Matrix t={t} rows={t.parties} kind={kind} by="party" />
            </Card>
          )}
        </>
      )}
    </>
  );
}
