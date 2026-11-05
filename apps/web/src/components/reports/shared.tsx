"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Select } from "@/components/ui/input";
import { formatAmount } from "@/lib/money";
import { cn } from "@/lib/utils";

/** "Oct 2026 (transition)" → "Oct 2026*" for chart axes. */
export const shortLabel = (label: string) => label.replace(" (transition)", "*");

const monthsLabel = (n: number) => (n === 0 ? "All time" : n === 1 ? "This month" : n === 12 ? "Last year" : n % 12 === 0 ? `Last ${n / 12} years` : `Last ${n} months`);

/** Months to show; 0 means all time (only where the report supports it). */
export function MonthsSelect({ value, onChange, options = [3, 6, 12, 24] }: { value: number; onChange: (n: number) => void; options?: number[] }) {
  return (
    <Select aria-label="Months" className="w-36" value={value} onChange={(e) => onChange(Number(e.target.value))}>
      {options.map((n) => <option key={n} value={n}>{monthsLabel(n)}</option>)}
    </Select>
  );
}

type Drill = { party_id?: string | null; employee_id?: string | null; payment_account_id?: string | null; direction?: string; from?: string; to?: string };

/** Link to Payment Entries already filtered to the payments behind a number. */
export function paymentsHref(f: Drill): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) q.set(k, v);
  return `/accounting/payment-entries?${q.toString()}`;
}

/** An amount that opens the payments behind it. Zero stays plain. */
export function DrillAmount({ value, drill, className, children }: { value: string; drill: Drill; className?: string; children?: ReactNode }) {
  const zero = /^-?0*(\.0*)?$/.test(value);
  const text = children ?? formatAmount(value);
  if (zero) return <span className={cn("text-muted-foreground", className)}>{text}</span>;
  return (
    <Link href={paymentsHref(drill)} className={cn("hover:underline", className)} title="Show these payments">
      {text}
    </Link>
  );
}

/** "+12.5%" / "−3.0%" with good/bad colouring; `goodWhenUp=false` for costs. */
export function ChangeText({ pct, value, goodWhenUp = true }: { pct?: string | null; value?: string | null; goodWhenUp?: boolean }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  const n = Number(value);
  if (n === 0) return <span className="text-muted-foreground">0</span>;
  const good = n > 0 === goodWhenUp;
  return (
    <span className={cn("tabular", good ? "text-success" : "text-destructive")}>
      {n > 0 ? "+" : ""}{formatAmount(value)}
      {pct !== null && pct !== undefined && <span className="ml-1 text-xs">({n > 0 ? "+" : ""}{pct}%)</span>}
    </span>
  );
}
