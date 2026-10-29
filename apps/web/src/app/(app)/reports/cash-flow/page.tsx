"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { num, PeriodChart, SERIES, Sparkline, StatTile, TrendChart } from "@/components/charts/charts";
import { ExportMenu } from "@/components/erp/export-menu";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { DrillAmount, MonthsSelect, shortLabel } from "@/components/reports/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatAmount, formatShort, sign, sum } from "@/lib/money";
import type { CashFlow } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Up to four currencies get their own line; the rest fold into "Other". */
function currencySeries(c: CashFlow) {
  const top = c.currencies.slice(0, c.currencies.length > 4 ? 3 : 4);
  const rest = c.currencies.slice(top.length);
  const lines = top.map((cur, i) => ({ key: cur.currency, label: cur.currency, color: SERIES[i]! }));
  if (rest.length) lines.push({ key: "Other", label: `Other (${rest.map((r) => r.currency).join(", ")})`, color: SERIES[3] });
  const data = c.periods.map((p, i) => {
    const row: Record<string, string | number> = { label: shortLabel(p.label) };
    for (const cur of top) row[cur.currency] = num(cur.values[i]);
    if (rest.length) row.Other = rest.reduce((n, cur) => n + num(cur.values[i]), 0);
    return row;
  });
  return { lines, data };
}

export default function CashFlowPage() {
  const [periods, setPeriods] = useState(12);
  const q = useQuery({
    queryKey: ["report-cash-flow", periods],
    queryFn: () => api.get<CashFlow>("/reports/cash-flow", { periods }),
    placeholderData: keepPreviousData,
  });
  const c = q.data;
  const base = c?.base_currency ?? "";
  const run = c?.runway;
  const negative = run && sign(run.cash_now) <= 0;
  const hasOther = !!c?.rows.some((r) => sign(r.other) !== 0);

  return (
    <>
      <PageHeader
        title="Cash flow & runway"
        description="Where money came from and went each month: income, expenses, salary and the owners' money. Transfers between your own accounts are left out. Also what you hold at each month end, and how long it lasts."
        actions={
          <>
            <MonthsSelect value={periods} onChange={setPeriods} />
            <ExportMenu path="/reports/cash-flow" params={{ periods: String(periods) }} />
          </>
        }
      />
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !c || !run ? <TableSkeleton /> : (
        <>
          {negative && (
            <Card className="mb-6 border-warning/50">
              <CardContent className="flex items-start gap-3 py-4 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                <p>
                  Your accounts add up to <strong className="tabular">{formatAmount(run.cash_now)} {base}</strong>: more has been recorded going out than coming in.
                  This usually means the balances you held before you started using the system haven&apos;t been entered. Record them as an
                  opening-balance <Link className="underline" href="/accounting/journal-entries">journal entry</Link> and the cash and runway figures will be right.
                </p>
              </CardContent>
            </Card>
          )}
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Cash now"
              value={formatAmount(run.cash_now)}
              unit={base}
              tone={negative ? "bad" : undefined}
              hint="All money accounts at today's rates"
              spark={<Sparkline values={c.rows.map((r) => num(r.closing_market))} label="Cash at each month end" />}
            />
            <StatTile label="Average income received" value={formatAmount(run.avg_in)} unit={base} hint={`Per month, last ${run.basis_periods} full month${run.basis_periods === 1 ? "" : "s"}`} />
            <StatTile label="Average spending" value={formatAmount(run.avg_out)} unit={base} hint={`Expenses + salary per month, last ${run.basis_periods} full month${run.basis_periods === 1 ? "" : "s"}`} />
            <StatTile
              label="Runway"
              value={negative ? "—" : run.months_net ? `${run.months_net} months` : sign(run.net_burn) <= 0 && run.basis_periods ? "Cash is growing" : "—"}
              tone={run.months_net && Number(run.months_net) < 6 ? "bad" : undefined}
              hint={
                negative ? "Needs opening balances" :
                run.basis_periods === 0 ? "Needs a full month of figures" :
                run.months_net ? `Spending ${formatAmount(run.net_burn)} more than comes in each month` :
                run.months_if_no_income ? `${run.months_if_no_income} months if no income came in` : undefined
              }
            />
          </div>

          <div className="mb-6 grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Income, spending and owner money</CardTitle>
                <CardDescription>Owner money is capital put in less drawings taken out. Transfers between your own accounts are left out.</CardDescription>
              </CardHeader>
              <CardContent>
                <PeriodChart
                  label="Income received, expenses and salary paid, and owner money per month"
                  data={c.periods.map((p, i) => {
                    const r = c.rows[i]!;
                    return { label: shortLabel(p.label), income: num(r.income), expenses: num(r.expenses), salary: num(r.salary), owner: num(r.owner_in) - num(r.owner_out) };
                  })}
                  unit={base}
                  bars={[
                    { key: "income", label: "Income", color: SERIES[0] },
                    { key: "expenses", label: "Expenses", color: SERIES[1], stack: "out" },
                    { key: "salary", label: "Salary", color: SERIES[2], stack: "out" },
                    { key: "owner", label: "Owner money (in − out)", color: SERIES[3] },
                  ]}
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Cash held</CardTitle><CardDescription>At each month end: as recorded, and at the saved exchange rates.</CardDescription></CardHeader>
              <CardContent>
                <TrendChart
                  label="Cash held at each month end"
                  data={c.periods.map((p, i) => ({ label: shortLabel(p.label), book: num(c.rows[i]!.closing_book), market: num(c.rows[i]!.closing_market) }))}
                  unit={base}
                  lines={[{ key: "market", label: "At saved rates", color: SERIES[0] }, { key: "book", label: "As recorded", color: SERIES[2] }]}
                />
              </CardContent>
            </Card>
          </div>

          {c.currencies.length > 0 && (() => {
            const { lines, data } = currencySeries(c);
            return (
              <Card className="mb-6">
                <CardHeader><CardTitle>By currency</CardTitle><CardDescription>Value in {base} of what you hold in each currency, at each month end.</CardDescription></CardHeader>
                <CardContent className="grid gap-6 xl:grid-cols-[2fr_1fr]">
                  <TrendChart label="Value held per currency" data={data} lines={lines} unit={base} />
                  <Table>
                    <THead><TR><TH>Currency</TH><TH className="text-right">Held now</TH><TH className="text-right">Value ({base})</TH><TH className="text-right">Share</TH></TR></THead>
                    <TBody>
                      {c.currencies.map((cur) => (
                        <TR key={cur.currency}>
                          <TD className="font-medium">{cur.currency}</TD>
                          <TD className="tabular text-right">{formatShort(cur.units.at(-1) ?? "0", 2)}</TD>
                          <TD className={cn("tabular text-right", sign(cur.values.at(-1)) < 0 && "text-destructive")}>{formatAmount(cur.values.at(-1))}</TD>
                          <TD className="tabular text-right text-muted-foreground">{cur.share_pct ? `${cur.share_pct}%` : "—"}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </CardContent>
              </Card>
            );
          })()}

          <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
            <Card className="overflow-x-auto">
              <CardHeader><CardTitle>Per month</CardTitle></CardHeader>
              <Table>
                <THead>
                  <TR>
                    <TH>Month</TH>
                    <TH className="text-right">Income</TH>
                    <TH className="text-right">Expenses</TH>
                    <TH className="text-right">Salary</TH>
                    <TH className="text-right" title="Capital the owners put in">Owner in</TH>
                    <TH className="text-right" title="Drawings the owners took out">Owner out</TH>
                    {hasOther && <TH className="text-right" title="Loans and other balance-sheet items">Other</TH>}
                    <TH className="text-right">Net change</TH>
                    <TH className="text-right">Closing (at rates)</TH>
                    <TH className="text-right" title="Payment fees the company paid">Fees</TH>
                    <TH className="text-right" title="Realized gain or loss on currency and crypto">FX gain/loss</TH>
                  </TR>
                </THead>
                <TBody>
                  {[...c.periods].map((p, i) => ({ p, r: c.rows[i]! })).reverse().map(({ p, r }) => (
                    <TR key={p.id}>
                      <TD className="whitespace-nowrap font-medium">{p.label}{p.in_progress && <span className="ml-1 text-xs font-normal text-muted-foreground">so far</span>}</TD>
                      <TD className="tabular text-right"><DrillAmount value={r.income} drill={{ direction: "receive", from: p.start_date, to: p.end_date }} /></TD>
                      <TD className="tabular text-right"><DrillAmount value={r.expenses} drill={{ direction: "pay", from: p.start_date, to: p.end_date }} /></TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(r.salary)}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(r.owner_in)}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(r.owner_out)}</TD>
                      {hasOther && <TD className="tabular text-right text-muted-foreground">{formatAmount(r.other)}</TD>}
                      <TD className={cn("tabular text-right", sign(r.net) < 0 && "text-destructive")}>{formatAmount(r.net)}</TD>
                      <TD className={cn("tabular text-right font-medium", sign(r.closing_market) < 0 && "text-destructive")}>{formatAmount(r.closing_market)}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(r.fees)}</TD>
                      <TD className={cn("tabular text-right", sign(r.fx_gain_loss) < 0 ? "text-destructive" : "text-muted-foreground")}>{formatAmount(r.fx_gain_loss)}</TD>
                    </TR>
                  ))}
                  <TR className="font-medium">
                    <TD>Total ({base})</TD>
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.income)))}</TD>
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.expenses)))}</TD>
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.salary)))}</TD>
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.owner_in)))}</TD>
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.owner_out)))}</TD>
                    {hasOther && <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.other)))}</TD>}
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.net)))}</TD>
                    <TD />
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.fees)))}</TD>
                    <TD className="tabular text-right">{formatAmount(sum(c.rows.map((r) => r.fx_gain_loss)))}</TD>
                  </TR>
                </TBody>
              </Table>
            </Card>
            <Card>
              <CardHeader><CardTitle>Fees by account</CardTitle><CardDescription>Payment fees in these months, by who paid them.</CardDescription></CardHeader>
              <CardContent>
                {c.fees_by_account.length === 0 ? <p className="text-sm text-muted-foreground">No fees recorded.</p> : (
                  <ul className="flex flex-col divide-y text-sm">
                    {c.fees_by_account.map((f, i) => (
                      <li key={i} className="flex items-center justify-between gap-3 py-2">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{f.account_name}</span>
                          <span className="text-xs text-muted-foreground">{f.payments} payment{f.payments === 1 ? "" : "s"} · paid by {f.paid_by === "company" ? "us" : "the client"}</span>
                        </span>
                        <span className="tabular">{formatAmount(f.amount)} {base}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
