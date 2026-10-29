"use client";

import { useQuery } from "@tanstack/react-query";

import { num, PeriodChart, SERIES, TrendChart } from "@/components/charts/charts";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { shortLabel } from "@/components/reports/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, sign } from "@/lib/money";
import type { ProjectFinancials, ProjectTrend } from "@/lib/types";
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

/** Month by month (salary periods): revenue and costs, and running totals against budget. */
function ProjectTrendView({ projectId }: { projectId: string }) {
  const q = useQuery({ queryKey: ["project-trend", projectId], queryFn: () => api.get<ProjectTrend>(`/projects/${projectId}/financials/trend`, { periods: 12 }) });
  const t = q.data;
  if (!t) return null;
  const earlier = num(t.before.cumulative_revenue) !== 0 || num(t.before.cumulative_costs) !== 0;
  // Start where the project has activity, so a new project is not a row of empty months.
  const firstActive = t.rows.findIndex((r) => num(r.revenue) !== 0 || num(r.costs) !== 0);
  if (firstActive < 0 && !earlier) return null;
  const from = earlier ? 0 : firstActive;
  const months = t.periods.slice(from).map((p, k) => ({ p, r: t.rows[from + k]! }));
  const flows = months.map(({ p, r }) => ({ label: shortLabel(p.label), revenue: num(r.revenue), costs: num(r.costs), profit: num(r.profit) }));
  const running = months.map(({ p, r }) => ({
    label: shortLabel(p.label),
    revenue: num(r.cumulative_revenue),
    costs: num(r.cumulative_costs),
    ...(t.budget ? { budget: num(t.budget) } : {}),
  }));
  return (
    <div className="grid gap-6 lg:col-span-2 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Per month</CardTitle><CardDescription>Revenue and costs (expenses + salary) in each salary period.</CardDescription></CardHeader>
        <CardContent>
          <PeriodChart
            label="Project revenue, costs and profit per month"
            data={flows}
            unit={t.base_currency}
            height={220}
            bars={[{ key: "revenue", label: "Revenue", color: SERIES[0] }, { key: "costs", label: "Costs", color: SERIES[1] }]}
            line={{ key: "profit", label: "Profit", color: SERIES[3] }}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Running totals</CardTitle><CardDescription>{t.budget ? "Costs so far against the budget." : "Revenue and costs so far. Set a budget on the project to track against it."}</CardDescription></CardHeader>
        <CardContent>
          <TrendChart
            label="Cumulative revenue and costs"
            data={running}
            unit={t.base_currency}
            height={220}
            lines={[
              { key: "revenue", label: "Revenue so far", color: SERIES[0] },
              { key: "costs", label: "Costs so far", color: SERIES[1] },
              ...(t.budget ? [{ key: "budget", label: "Budget", color: SERIES[2] }] : []),
            ]}
          />
        </CardContent>
      </Card>
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
              {f.hours_used_pct && <span className={cn(Number(f.hours_used_pct) > 100 && "text-destructive")}> ({f.hours_used_pct}%)</span>}
            </p>
            {f.revenue_per_hour && <p className="text-muted-foreground">{formatAmount(f.revenue_per_hour)} {f.base_currency} revenue per hour logged</p>}
          </CardContent>
        </Card>
      </div>
      <ProjectTrendView projectId={projectId} />
    </div>
  );
}
