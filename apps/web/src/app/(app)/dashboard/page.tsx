"use client";

import { ArrowRight, CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/erp/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { useMe } from "@/lib/session";

const PHASES = [
  { n: 1, title: "Foundation", body: "Sign-in, roles & permissions, audit log, company settings, currencies, custom categories." },
  { n: 2, title: "Accounting & Payments", body: "Chart of accounts, general ledger, payment entries, parties, employee revenue split." },
  { n: 3, title: "Salary", body: "Salary formulas, salary periods (e.g. 25th–24th), statements, salary payments." },
  { n: 4, title: "Projects", body: "Projects, tasks, Kanban, Gantt timeline, project financials." },
  { n: 5, title: "Calendar & Reporting", body: "Calendars, dashboards, financial and employee reports, exports." },
  { n: 6, title: "Production readiness", body: "Hardening, backups, monitoring, documentation." },
];
const CURRENT_PHASE = 1;

export default function DashboardPage() {
  const me = useMe();
  const firstName = me.full_name.split(/\s+/)[0];
  const quickLinks = [
    { href: "/settings/company", label: "Company settings", show: true },
    { href: "/settings/users", label: "Invite users", show: "users.manage" in me.permissions },
    { href: "/settings/categories", label: "Custom categories", show: true },
    { href: "/settings/currencies", label: "Currencies & exchange rates", show: true },
    { href: "/settings/audit-logs", label: "Audit log", show: "audit.read" in me.permissions },
  ].filter((l) => l.show);

  return (
    <>
      <PageHeader
        title={`Welcome, ${firstName}`}
        description="Financial KPIs (income, expenses, cash, revenue by employee and project) appear here once accounting goes live in Phase 2."
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Rollout</CardTitle>
            <CardDescription>What is available now and what comes next.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="flex flex-col gap-4">
              {PHASES.map((p) => {
                const done = p.n <= CURRENT_PHASE;
                return (
                  <li key={p.n} className="flex gap-3">
                    {done ? (
                      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-label="Available" />
                    ) : (
                      <Circle className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-label="Planned" />
                    )}
                    <div>
                      <p className="font-medium">
                        Phase {p.n} · {p.title}
                      </p>
                      <p className="text-sm text-muted-foreground">{p.body}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Get set up</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col">
              {quickLinks.map((l) => (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    className="flex items-center justify-between rounded-md px-2 py-2 text-sm hover:bg-muted"
                  >
                    {l.label}
                    <ArrowRight className="size-4 text-muted-foreground" />
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
