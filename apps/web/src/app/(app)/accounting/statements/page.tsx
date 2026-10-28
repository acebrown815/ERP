"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useState } from "react";

import { CsvButton, DateRange, yearRange } from "@/components/accounting/report-controls";
import { PageHeader } from "@/components/erp/page-header";
import { ProjectPicker } from "@/components/erp/pickers";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, sum } from "@/lib/money";
import { useCompany } from "@/lib/queries";
import type { BalanceSheet, ProfitLoss, StatementRow, TrialBalance } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tab = "pl" | "bs" | "tb";
const TABS: { key: Tab; label: string }[] = [
  { key: "pl", label: "Profit & loss" },
  { key: "bs", label: "Balance sheet" },
  { key: "tb", label: "Trial balance" },
];

function Rows({ rows }: { rows: StatementRow[] }) {
  return rows.map((r) => (
    <tr key={r.account_id} className={cn("border-b last:border-0", r.is_group && "font-medium")}>
      <td className="py-1.5" style={{ paddingLeft: 12 + r.depth * 18 }}>
        <span className="font-mono text-xs text-muted-foreground">{r.code}</span> {r.name}
      </td>
      <td className={cn("tabular px-3 py-1.5 text-right", r.is_group && r.depth === 0 && "text-muted-foreground")}>{formatAmount(r.amount)}</td>
    </tr>
  ));
}

function Section({ title, rows, total, totalLabel }: { title: string; rows: StatementRow[]; total?: string; totalLabel?: string }) {
  return (
    <>
      <tr className="bg-muted/50"><th colSpan={2} className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</th></tr>
      {rows.length ? <Rows rows={rows} /> : <tr><td colSpan={2} className="px-3 py-2 text-sm text-muted-foreground">Nothing posted</td></tr>}
      {total !== undefined && (
        <tr className="border-t font-semibold">
          <td className="px-3 py-2">{totalLabel}</td>
          <td className="tabular px-3 py-2 text-right">{formatAmount(total)}</td>
        </tr>
      )}
    </>
  );
}

function ProfitAndLoss({ range, projectId }: { range: { from: string; to: string }; projectId: string | null }) {
  const q = useQuery({
    queryKey: ["pl", range, projectId],
    queryFn: () => api.get<ProfitLoss>("/reports/profit-and-loss", { ...range, project_id: projectId }),
    placeholderData: keepPreviousData,
  });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <TableSkeleton />;
  const d = q.data;
  return (
    <table className="w-full text-sm">
      <tbody>
        <Section title="Income" rows={d.income} total={d.total_income} totalLabel="Total income" />
        <Section title="Expenses" rows={d.expenses} total={d.total_expenses} totalLabel="Total expenses" />
        <tr className="border-t-2 text-base font-semibold">
          <td className="px-3 py-3">Net profit</td>
          <td className={cn("tabular px-3 py-3 text-right", Number(d.net_profit) < 0 && "text-destructive")}>{formatAmount(d.net_profit)}</td>
        </tr>
      </tbody>
    </table>
  );
}

function BalanceSheetView({ asOf }: { asOf: string }) {
  const q = useQuery({ queryKey: ["bs", asOf], queryFn: () => api.get<BalanceSheet>("/reports/balance-sheet", { as_of: asOf }), placeholderData: keepPreviousData });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <TableSkeleton />;
  const d = q.data;
  return (
    <>
      <div className={cn("flex items-center gap-2 border-b px-3 py-2 text-sm", d.balanced ? "text-success" : "text-destructive")}>
        {d.balanced ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
        {d.balanced ? "Assets = Liabilities + Equity" : "Out of balance. Contact your administrator."}
      </div>
      <table className="w-full text-sm">
        <tbody>
          <Section title="Assets" rows={d.assets} total={d.total_assets} totalLabel="Total assets" />
          <Section title="Liabilities" rows={d.liabilities} total={d.total_liabilities} totalLabel="Total liabilities" />
          <Section title="Equity" rows={d.equity} />
          <tr className="border-b">
            <td className="px-3 py-1.5 italic text-muted-foreground">Current earnings (not yet closed to retained earnings)</td>
            <td className="tabular px-3 py-1.5 text-right">{formatAmount(d.unclosed_earnings)}</td>
          </tr>
          <tr className="border-t font-semibold">
            <td className="px-3 py-2">Total equity</td>
            <td className="tabular px-3 py-2 text-right">{formatAmount(d.total_equity)}</td>
          </tr>
          <tr className="border-t-2 text-base font-semibold">
            <td className="px-3 py-3">Liabilities + equity</td>
            <td className="tabular px-3 py-3 text-right">{formatAmount(sum([d.total_liabilities, d.total_equity]))}</td>
          </tr>
        </tbody>
      </table>
    </>
  );
}

function TrialBalanceView({ range }: { range: { from: string; to: string } }) {
  const q = useQuery({ queryKey: ["tb", range], queryFn: () => api.get<TrialBalance>("/reports/trial-balance", range), placeholderData: keepPreviousData });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <TableSkeleton />;
  const cols = ["opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit"] as const;
  const t = q.data.totals;
  const ties = t && t.debit === t.credit && t.closing_debit === t.closing_credit;
  return (
    <div className="overflow-x-auto">
      <div className={cn("flex items-center gap-2 border-b px-3 py-2 text-sm", ties ? "text-success" : "text-destructive")}>
        {ties ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />} {ties ? "Debits equal credits" : "Totals don't tie"}
      </div>
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Account</th>
            <th className="px-3 py-2 text-right font-medium" colSpan={2}>Opening</th>
            <th className="px-3 py-2 text-right font-medium" colSpan={2}>Period</th>
            <th className="px-3 py-2 text-right font-medium" colSpan={2}>Closing</th>
          </tr>
          <tr>
            <th />
            {["Dr", "Cr", "Dr", "Cr", "Dr", "Cr"].map((h, i) => <th key={i} className="px-3 pb-2 text-right font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="tabular">
          {q.data.rows.map((r) => (
            <tr key={r.account_id} className="border-b">
              <td className="px-3 py-1.5"><span className="font-mono text-xs text-muted-foreground">{r.code}</span> {r.name}</td>
              {cols.map((c) => <td key={c} className="px-3 py-1.5 text-right">{Number(r[c]) ? formatAmount(r[c]) : ""}</td>)}
            </tr>
          ))}
        </tbody>
        {t && (
          <tfoot className="tabular border-t-2 font-semibold">
            <tr>
              <td className="px-3 py-2">Total</td>
              {cols.map((c) => <td key={c} className="px-3 py-2 text-right">{formatAmount(t[c])}</td>)}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

export default function StatementsPage() {
  const base = useCompany().data?.base_currency ?? "USD";
  const [tab, setTab] = useState<Tab>("pl");
  const [range, setRange] = useState(yearRange());
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [projectId, setProjectId] = useState<string | null>(null);
  const csv = tab === "pl" ? { path: "/reports/profit-and-loss", params: { ...range, project_id: projectId } }
    : tab === "bs" ? { path: "/reports/balance-sheet", params: { as_of: asOf } }
      : { path: "/reports/trial-balance", params: range };

  return (
    <>
      <PageHeader title="Financial statements" description={`Computed from the posted ledger, in ${base}.`} actions={<CsvButton {...csv} />} />
      <div role="tablist" aria-label="Statement" className="mb-4 flex gap-1 rounded-lg border bg-card p-1 sm:w-fit">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={cn("flex-1 rounded-md px-3 py-1.5 text-sm sm:flex-none", tab === t.key ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground")}>
            {t.label}
          </button>
        ))}
      </div>
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 border-b py-3">
          {tab === "bs" ? (
            <label className="flex items-center gap-2 text-sm">As of <Input type="date" className="w-40" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
          ) : <DateRange {...range} onChange={setRange} />}
          {tab === "pl" && <div className="w-64"><ProjectPicker value={projectId} onChange={setProjectId} placeholder="All projects" /></div>}
        </CardContent>
        {tab === "pl" ? <ProfitAndLoss range={range} projectId={projectId} /> : tab === "bs" ? <BalanceSheetView asOf={asOf} /> : <TrialBalanceView range={range} />}
      </Card>
    </>
  );
}
