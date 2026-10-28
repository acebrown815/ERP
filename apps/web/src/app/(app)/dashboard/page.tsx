"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Circle, Plus } from "lucide-react";
import Link from "next/link";

import { monthRange } from "@/components/accounting/report-controls";
import { PageHeader } from "@/components/erp/page-header";
import { StatusBadge } from "@/components/payments/entry-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, sum } from "@/lib/money";
import { currencyPrecision, useAccounts, useCompany, useCurrencies } from "@/lib/queries";
import { useMe } from "@/lib/session";
import type { Page, PaymentEntry, ProfitLoss } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const PHASES = [
  { n: 1, title: "Foundation", body: "Sign-in, roles & permissions, audit log, company settings, currencies, custom categories." },
  { n: 2, title: "Accounting & Payments", body: "Chart of accounts, general ledger, payment entries, parties, employee revenue split, reports, import." },
  { n: 3, title: "Salary", body: "Salary formulas, salary periods (e.g. 25th–24th), statements, salary payments." },
  { n: 4, title: "Projects", body: "Tasks, Kanban, Gantt timeline, project financials." },
  { n: 5, title: "Calendar & Reporting", body: "Calendars, dashboards, employee and project reports, exports." },
  { n: 6, title: "Production readiness", body: "Hardening, backups, monitoring, documentation." },
];
const CURRENT_PHASE = 2;
const MONEY_TYPES = ["bank", "cash", "crypto_wallet"];

function Kpi({ label, value, base, tone }: { label: string; value: string | undefined; base: string; tone?: "good" | "bad" }) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        {value === undefined ? <Skeleton className="mt-1 h-8 w-32" /> : (
          <p className={`tabular mt-1 text-2xl font-semibold ${tone === "bad" ? "text-destructive" : tone === "good" ? "text-success" : ""}`}>
            {formatAmount(value)} <span className="text-sm font-normal text-muted-foreground">{base}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function FinanceOverview() {
  const base = useCompany().data?.base_currency ?? "USD";
  const currencies = useCurrencies();
  const accounts = useAccounts();
  const month = monthRange();
  const pl = useQuery({ queryKey: ["pl", month, null], queryFn: () => api.get<ProfitLoss>("/reports/profit-and-loss", month) });
  const recent = useQuery({ queryKey: ["payment-entries", "recent"], queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { page_size: 6 }) });
  const cash = accounts.data ? sum(accounts.data.filter((a) => !a.is_group && MONEY_TYPES.includes(a.account_type)).map((a) => a.balance)) : undefined;
  return (
    <>
      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Cash, bank & wallets" value={cash} base={base} />
        <Kpi label="Income this month" value={pl.data?.total_income} base={base} />
        <Kpi label="Expenses this month" value={pl.data?.total_expenses} base={base} />
        <Kpi label="Net profit this month" value={pl.data?.net_profit} base={base} tone={pl.data && Number(pl.data.net_profit) < 0 ? "bad" : "good"} />
      </div>
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
                    <span className="tabular">{e.direction === "pay" ? "−" : ""}{formatAmount(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}</span>
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

export default function DashboardPage() {
  const me = useMe();
  const firstName = me.full_name.split(/\s+/)[0];
  const finance = "reports.financial" in me.permissions;
  const quickLinks = [
    { href: "/accounting/payment-entries/new", label: "Record a payment", show: "payments.create" in me.permissions },
    { href: "/parties/customers", label: "Customers", show: "parties.read" in me.permissions },
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
