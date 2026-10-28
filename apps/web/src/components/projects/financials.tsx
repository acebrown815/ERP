"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import type { ProjectFinancials } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ProgressBar } from "./shared";

function Row({ label, value, hint, strong, negative }: { label: string; value: string | null | undefined; hint?: string; strong?: boolean; negative?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4 py-1.5", strong && "border-t pt-2 font-semibold")}>
      <span>
        {label}
        {hint && <span className="block text-xs font-normal text-muted-foreground">{hint}</span>}
      </span>
      <span className={cn("tabular", negative && sign(value) > 0 && "text-muted-foreground", value && sign(value) < 0 && strong && "text-destructive")}>
        {value == null ? "—" : `${negative && sign(value) > 0 ? "−" : ""}${formatAmount(value)}`}
      </span>
    </div>
  );
}

/** Project profit from the ledger (docs/architecture.md, Section 11.1). */
export function ProjectFinancialsView({ projectId }: { projectId: string }) {
  const q = useQuery({ queryKey: ["project-financials", projectId], queryFn: () => api.get<ProjectFinancials>(`/projects/${projectId}/financials`) });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const f = q.data;
  if (!f) return <TableSkeleton rows={6} />;
  const budgetPct = f.budget && sign(f.budget) > 0 ? String((Number(f.budget_used) / Number(f.budget)) * 100) : null;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Profit</CardTitle>
          <CardDescription>From posted payments tagged with this project ({f.base_currency}). Cash basis: money received is revenue.</CardDescription>
        </CardHeader>
        <CardContent className="text-sm">
          <Row label="Revenue received" value={f.revenue} hint={sign(f.revenue) !== sign(f.attributed_revenue) || f.revenue !== f.attributed_revenue ? `Credited to employees: ${formatAmount(f.attributed_revenue)}` : undefined} />
          <Row label="Direct expenses" value={f.direct_expenses} negative />
          <Row label="Salary paid" value={f.salary_paid} negative hint="Salary payments split by the employee's revenue on this project" />
          <Row label="Profit (cash)" value={f.profit_cash} strong hint={f.margin_pct != null ? `${f.margin_pct}% margin` : undefined} />
          <Row label="Salary earned, not paid yet" value={f.salary_owed} negative />
          <Row label="Profit after salary owed" value={f.profit_incl_owed} strong />
        </CardContent>
      </Card>
      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader><CardTitle>Contract and budget</CardTitle></CardHeader>
          <CardContent className="text-sm">
            <Row label="Contract value" value={f.contract_value} />
            <Row label="Still to receive" value={f.contract_remaining} />
            <Row label="Budget" value={f.budget} />
            <Row label="Spent (expenses + salary)" value={f.budget_used} />
            <Row label="Budget left" value={f.budget_remaining} strong />
            {budgetPct && <ProgressBar value={budgetPct} className="mt-2" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Delivery</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <ProgressBar value={f.completion_pct} />
            <p className="text-muted-foreground">
              {f.tasks_done} of {f.tasks_total} tasks done
              {f.tasks_overdue > 0 && <span className="text-destructive"> · {f.tasks_overdue} overdue</span>} · {formatAmount(f.logged_hours, 1)} h logged
              {sign(f.estimate_hours) > 0 && ` of ${formatAmount(f.estimate_hours, 1)} h estimated`}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
