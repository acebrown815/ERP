"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ChevronDown, ChevronRight, Circle, Plus } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";

import { rangeText, usePeriodRanges } from "@/components/accounting/report-controls";
import { PageHeader } from "@/components/erp/page-header";
import { StatusBadge } from "@/components/payments/entry-view";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, formatShort, sign, subtract } from "@/lib/money";
import { currencyPrecision, useCompany, useCurrencies } from "@/lib/queries";
import { useMe } from "@/lib/session";
import type { Holdings, Page, PaymentEntry, ProfitLoss } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const PHASES = [
  { n: 1, title: "Foundation", body: "Sign-in, roles & permissions, audit log, company settings, currencies, custom categories." },
  { n: 2, title: "Accounting & Payments", body: "Chart of accounts, general ledger, payment entries, parties, employee revenue split, reports, import." },
  { n: 3, title: "Salary", body: "Salary formulas, salary periods (e.g. 25th–24th), statements, salary payments." },
  { n: 4, title: "Projects", body: "Tasks, Kanban, Gantt timeline, project financials." },
  { n: 5, title: "Calendar & Reporting", body: "Calendars, dashboards, employee and project reports, exports." },
  { n: 6, title: "Production readiness", body: "Hardening, backups, monitoring, documentation." },
];
const CURRENT_PHASE = 3;

function Kpi({ label, value, base, tone, hint }: { label: string; value: string | undefined; base: string; tone?: "good" | "bad"; hint?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        {value === undefined ? <Skeleton className="mt-1 h-8 w-32" /> : (
          <p className={`tabular mt-1 text-2xl font-semibold ${tone === "bad" ? "text-destructive" : tone === "good" ? "text-success" : ""}`}>
            {formatAmount(value)} <span className="text-sm font-normal text-muted-foreground">{base}</span>
          </p>
        )}
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function FinanceOverview() {
  const base = useCompany().data?.base_currency ?? "USD";
  const currencies = useCurrencies();
  const holdings = useQuery({ queryKey: ["holdings"], queryFn: () => api.get<Holdings>("/reports/holdings") });
  // "This month" follows the salary cycle (e.g. Oct 25 – Nov 24), not the calendar month.
  const { current, loading } = usePeriodRanges();
  const month = { from: current.from, to: current.to };
  const pl = useQuery({
    queryKey: ["pl", month, null],
    queryFn: () => api.get<ProfitLoss>("/reports/profit-and-loss", month),
    enabled: !loading,
  });
  const span = `${current.label} · ${rangeText(current)}`;
  const recent = useQuery({ queryKey: ["payment-entries", "recent"], queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { page_size: 6 }) });
  const h = holdings.data;
  const fx = h ? subtract(h.market_total, h.book_total) : "0";
  return (
    <>
      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Cash, bank & wallets"
          value={h?.market_total}
          base={base}
          hint={h && sign(fx) ? `At today's rates · ${formatAmount(h.book_total)} as recorded` : "At today's rates"}
        />
        <Kpi label="Income this month" value={pl.data?.total_income} base={base} hint={span} />
        <Kpi label="Expenses this month" value={pl.data?.total_expenses} base={base} hint={span} />
        <Kpi label="Net profit this month" value={pl.data?.net_profit} base={base} tone={pl.data && sign(pl.data.net_profit) < 0 ? "bad" : "good"} hint={span} />
      </div>
      {h && <AssetsByCurrency holdings={h} />}
      <Card className="mb-6">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Recent payments</CardTitle>
          <Button variant="ghost" size="sm" asChild><Link href="/accounting/payment-entries">All payments <ArrowRight /></Link></Button>
        </CardHeader>
        <CardContent>
          {!recent.data ? <Skeleton className="h-24 w-full" /> : recent.data.items.length === 0 ? (
            <div className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
              No payments yet.
              <Button size="sm" asChild><Link href="/accounting/payment-entries/new"><Plus /> Record the first payment</Link></Button>
            </div>
          ) : (
            <ul className="divide-y">
              {recent.data.items.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <Link href={`/accounting/payment-entries/${e.id}`} className="min-w-0 hover:underline">
                    <span className="font-mono text-xs text-muted-foreground">{e.number}</span>{" "}
                    {e.party_name ?? (e.direction === "internal_transfer" ? "Internal transfer" : "—")}
                    <span className="text-muted-foreground"> · {formatDate(e.posting_date)}</span>
                  </Link>
                  <span className="flex shrink-0 items-center gap-3">
                    <span className="tabular">{e.direction === "pay" ? "−" : ""}{formatShort(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}</span>
                    <StatusBadge status={e.status} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}

/** Money held per currency: units, recorded value, and value at the saved rate (display only, nothing posted). */
function AssetsByCurrency({ holdings }: { holdings: Holdings }) {
  const currencies = useCurrencies();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const base = holdings.base_currency;
  const shown = holdings.currencies.filter((c) => sign(c.units) !== 0 || sign(c.book_value) !== 0);
  const totalDiff = subtract(holdings.market_total, holdings.book_total);
  const toggle = (code: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(code)) n.delete(code);
      else n.add(code);
      return n;
    });
  return (
    <Card className="mb-6">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>Assets by currency</CardTitle>
          <CardDescription>
            Cash, bank accounts, wallets and cards in their own currency. &quot;At today&apos;s rate&quot; uses the latest saved rate
            (Settings → Currencies &amp; Rates); &quot;as recorded&quot; is what the books hold.
          </CardDescription>
        </div>
        <Button variant="ghost" size="sm" asChild><Link href="/settings/currencies">Rates <ArrowRight /></Link></Button>
      </CardHeader>
      <CardContent>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">No money held yet.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="w-8" />
                <TH>Currency</TH>
                <TH className="text-right">Amount held</TH>
                <TH className="text-right">Rate</TH>
                <TH className="text-right">At today&apos;s rate ({base})</TH>
                <TH className="text-right">As recorded ({base})</TH>
                <TH className="text-right">Difference</TH>
              </TR>
            </THead>
            <TBody>
              {shown.map((c) => {
                const expanded = open.has(c.currency);
                const diff = c.market_value != null ? subtract(c.market_value, c.book_value) : null;
                const precision = currencyPrecision(currencies.data, c.currency);
                return (
                  <Fragment key={c.currency}>
                    <TR>
                      <TD>
                        <Button variant="ghost" size="icon" aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} ${c.currency} accounts`} onClick={() => toggle(c.currency)}>
                          {expanded ? <ChevronDown /> : <ChevronRight />}
                        </Button>
                      </TD>
                      <TD className="font-medium">{c.currency}</TD>
                      <TD className="tabular text-right">{formatShort(c.units, precision)} {c.currency}</TD>
                      <TD className="tabular text-right">
                        {c.currency === base ? "—" : c.rate ? (
                          <span title={c.rate_date ? `Saved for ${formatDate(c.rate_date)}` : undefined}>{formatAmount(c.rate, 4)}</span>
                        ) : <span className="text-warning">no rate</span>}
                      </TD>
                      <TD className="tabular text-right font-medium">{c.market_value != null ? formatAmount(c.market_value) : "—"}</TD>
                      <TD className="tabular text-right text-muted-foreground">{formatAmount(c.book_value)}</TD>
                      <TD className={cn("tabular text-right", diff && sign(diff) < 0 && "text-destructive", diff && sign(diff) > 0 && "text-success")}>
                        {diff && sign(diff) ? `${sign(diff) > 0 ? "+" : ""}${formatAmount(diff)}` : "—"}
                      </TD>
                    </TR>
                    {expanded && c.accounts.map((a) => (
                      <TR key={a.account_id} className="bg-muted/30 text-sm">
                        <TD />
                        <TD className="pl-6 text-muted-foreground">{a.code} {a.name}</TD>
                        <TD className="tabular text-right">{formatShort(a.units, precision)}</TD>
                        <TD />
                        <TD className="tabular text-right">{a.market_value != null ? formatAmount(a.market_value) : "—"}</TD>
                        <TD className="tabular text-right text-muted-foreground">{formatAmount(a.book_value)}</TD>
                        <TD />
                      </TR>
                    ))}
                  </Fragment>
                );
              })}
              <TR className="font-medium">
                <TD />
                <TD>Total</TD>
                <TD />
                <TD />
                <TD className="tabular text-right">{formatAmount(holdings.market_total)}</TD>
                <TD className="tabular text-right text-muted-foreground">{formatAmount(holdings.book_total)}</TD>
                <TD className="tabular text-right">{sign(totalDiff) ? formatAmount(totalDiff) : "—"}</TD>
              </TR>
            </TBody>
          </Table>
        )}
        {holdings.missing_rates.length > 0 && (
          <p className="mt-3 text-xs text-warning">No saved rate for {holdings.missing_rates.join(", ")}: counted at the recorded value in the total.</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const me = useMe();
  const firstName = me.full_name.split(/\s+/)[0];
  const finance = "reports.financial" in me.permissions;
  const quickLinks = [
    { href: "/accounting/payment-entries/new", label: "Record a payment", show: "payments.create" in me.permissions },
    { href: "/parties/customers", label: "Customers", show: "parties.read" in me.permissions },
    { href: "/me", label: "My salary", show: "salary.read" in me.permissions && !finance },
    { href: "/employees/salary", label: "Salary board", show: "salary.read" in me.permissions && finance },
    { href: "/employees", label: "Employees", show: "employees.read" in me.permissions },
    { href: "/projects", label: "Projects", show: "projects.read" in me.permissions },
    { href: "/settings/imports", label: "Import existing data", show: "imports.manage" in me.permissions },
    { href: "/settings/company", label: "Company settings", show: true },
  ].filter((l) => l.show);

  return (
    <>
      <PageHeader title={`Welcome, ${firstName}`} description={finance ? "This month at a glance, from the posted ledger." : undefined} />
      {finance && <FinanceOverview />}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Rollout</CardTitle>
            <CardDescription>What is available now and what comes next.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="flex flex-col gap-4">
              {PHASES.map((p) => (
                <li key={p.n} className="flex gap-3">
                  {p.n <= CURRENT_PHASE ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-label="Available" /> : <Circle className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-label="Planned" />}
                  <div>
                    <p className="font-medium">Phase {p.n} · {p.title}</p>
                    <p className="text-sm text-muted-foreground">{p.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Shortcuts</CardTitle></CardHeader>
          <CardContent>
            <ul className="flex flex-col">
              {quickLinks.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="flex items-center justify-between rounded-md px-2 py-2 text-sm hover:bg-muted">
                    {l.label} <ArrowRight className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
