"use client";

import { Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { formatAmount, sign } from "@/lib/money";
import type { FormulaDefinition, SalaryComponent, SalaryPeriod } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const STATUS: Record<string, { label: string; variant: "success" | "warning" | "muted" | "destructive" | "default" }> = {
  paid: { label: "Paid", variant: "success" },
  partially_paid: { label: "Partly paid", variant: "warning" },
  unpaid: { label: "Unpaid", variant: "destructive" },
  nothing_due: { label: "Nothing due", variant: "muted" },
};

export function SalaryStatus({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, variant: "default" as const };
  return <Badge variant={s.variant}>{s.label}</Badge>;
}

/** "0.104444…" → "10.44%". Rates are display-only here, so a float is fine. */
export function formatRate(rate: string | null | undefined, digits = 2): string {
  if (rate === null || rate === undefined || rate === "") return "—";
  return `${(Number(rate) * 100).toFixed(digits)}%`;
}

export function periodRange(p: { start_date: string; end_date: string }): string {
  return `${formatDate(p.start_date)} – ${formatDate(p.end_date)}`;
}

export function PeriodSelect({
  periods,
  value,
  onChange,
  id = "salary_period",
}: {
  periods: SalaryPeriod[];
  value: string | undefined;
  onChange: (id: string) => void;
  id?: string;
}) {
  return (
    <Select id={id} aria-label="Salary period" value={value ?? ""} onChange={(e) => onChange(e.target.value)} className="w-auto min-w-64">
      {periods.map((p) => (
        <option key={p.id} value={p.id}>
          {p.label} · {periodRange(p)}
          {p.is_current ? " · current" : p.status === "closed" ? " · closed" : p.is_future ? " · upcoming" : ""}
        </option>
      ))}
    </Select>
  );
}

/** The current period, else the newest one. */
export function defaultPeriod(periods: SalaryPeriod[] | undefined): SalaryPeriod | undefined {
  return periods?.find((p) => p.is_current) ?? periods?.[0];
}

/** Revenue share, fixed, bonuses, caps and adjustments, adding up to the calculated salary. */
export function Breakdown({ components, total, className }: { components: SalaryComponent[]; total: string; className?: string }) {
  return (
    <table className={cn("w-full text-sm", className)}>
      <tbody>
        {components.length === 0 && (
          <tr><td className="py-1 text-muted-foreground">No formula and no adjustments.</td><td /></tr>
        )}
        {components.map((c, i) => (
          <tr key={i}>
            <td className="py-1">
              {c.label}
              {c.component === "revenue_share" && c.basis && c.rate && (
                <span className="text-muted-foreground"> · {formatAmount(c.basis)} × {formatRate(c.rate, 4)}</span>
              )}
            </td>
            <td className="tabular py-1 text-right">{formatAmount(c.amount)}</td>
          </tr>
        ))}
        <tr className="border-t font-medium">
          <td className="py-1">Calculated salary</td>
          <td className="tabular py-1 text-right">{formatAmount(total)}</td>
        </tr>
      </tbody>
    </table>
  );
}

export const MODE_LABEL: Record<string, string> = {
  linear_curve: "Rate curve",
  flat_tiers: "Flat tiers",
  progressive_tiers: "Progressive tiers",
  none: "Fixed only",
};

/** One-line summary, e.g. "8.00% at 3,000 → 30.00% at 30,000 · + 500 fixed". */
export function summarize(d: FormulaDefinition): string {
  const s = d.rate_schedule;
  const parts: string[] = [];
  if (s.mode === "linear_curve") parts.push((s.points ?? []).map((p) => `${formatRate(String(p.rate))} at ${formatAmount(String(p.revenue), 0)}`).join(" → "));
  if (s.mode === "flat_tiers" || s.mode === "progressive_tiers")
    parts.push((s.tiers ?? []).map((t) => `${formatRate(String(t.rate))} from ${formatAmount(String(t.from_revenue), 0)}`).join(", "));
  if (sign(String(d.fixed_amount ?? "0"))) parts.push(`${formatAmount(String(d.fixed_amount))} fixed`);
  if (d.bonuses?.length) parts.push(`${d.bonuses.length} bonus rule${d.bonuses.length > 1 ? "s" : ""}`);
  return parts.join(" · ") || "Nothing";
}
