"use client";

import { Plus, Trash2, Wand2 } from "lucide-react";

import { EmployeePicker } from "@/components/erp/pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { formatAmount, sum } from "@/lib/money";
import type { Allocation } from "@/lib/types";
import { cn } from "@/lib/utils";

export type SplitMode = "percent" | "amount";
export type SplitDraft = { key: string; employee_id: string | null; value: string };

let counter = 0;
export const newSplitRow = (employee_id: string | null = null, value = ""): SplitDraft => ({
  key: `row-${++counter}`,
  employee_id,
  value,
});

/**
 * Revenue split for customer payments: who generated this revenue. Must cover exactly 100% (or the full
 * eligible amount) before the payment can be submitted (docs/architecture.md, Section 8).
 */
export function AllocationEditor({
  mode,
  onModeChange,
  rows,
  onChange,
  computed,
  eligible,
  baseCurrency,
  onUseProjectDefault,
  error,
  disabled,
}: {
  mode: SplitMode;
  onModeChange: (m: SplitMode) => void;
  rows: SplitDraft[];
  onChange: (rows: SplitDraft[]) => void;
  computed: Allocation[] | undefined;
  eligible: string | null | undefined;
  baseCurrency: string;
  onUseProjectDefault?: () => void;
  error?: string;
  disabled?: boolean;
}) {
  const total = sum(rows.map((r) => r.value));
  const target = mode === "percent" ? "100" : eligible ?? null;
  const complete = target !== null && sum([total, `-${target}`]) === "0";
  const pct = mode === "percent" ? Math.min(Number(total), 100) : eligible ? Math.min((Number(total) / Number(eligible)) * 100, 100) : 0;
  const amountFor = (employee_id: string | null) => computed?.find((a) => a.employee_id === employee_id)?.amount;
  const update = (key: string, patch: Partial<SplitDraft>) => onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Employee revenue split</CardTitle>
          <CardDescription>
            Optional. Who this revenue is credited to; it counts toward their salary. If you add employees, the split must cover 100%.
          </CardDescription>
        </div>
        <div className="flex gap-1 rounded-md border p-0.5 text-sm" role="radiogroup" aria-label="Split by">
          {(["percent", "amount"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              disabled={disabled}
              onClick={() => onModeChange(m)}
              className={cn("rounded px-2.5 py-1", mode === m ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground")}
            >
              {m === "percent" ? "Percent" : "Amount"}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {rows.length === 0 && <p className="text-sm text-muted-foreground">Add the employees who worked on this.</p>}
        {rows.map((r, i) => (
          <div key={r.key} className="grid grid-cols-[1fr_7rem_auto] items-center gap-2 sm:grid-cols-[1fr_8rem_8rem_auto]">
            <EmployeePicker
              id={`split-employee-${i}`}
              value={r.employee_id}
              disabled={disabled}
              onChange={(v) => update(r.key, { employee_id: v })}
            />
            <div className="relative">
              <Input
                aria-label={mode === "percent" ? "Percent" : "Amount"}
                inputMode="decimal"
                className="tabular pr-7 text-right"
                value={r.value}
                disabled={disabled}
                onChange={(e) => update(r.key, { value: e.target.value.trim() })}
              />
              <span className="pointer-events-none absolute right-2.5 top-2 text-sm text-muted-foreground">
                {mode === "percent" ? "%" : ""}
              </span>
            </div>
            <span className="tabular hidden text-right text-sm text-muted-foreground sm:block">
              {mode === "percent" && amountFor(r.employee_id) ? `${formatAmount(amountFor(r.employee_id))} ${baseCurrency}` : ""}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Remove row"
              disabled={disabled}
              onClick={() => onChange(rows.filter((x) => x.key !== r.key))}
            >
              <Trash2 />
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => onChange([...rows, newSplitRow()])}>
            <Plus /> Add employee
          </Button>
          {onUseProjectDefault && (
            <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={onUseProjectDefault}>
              <Wand2 /> Use project default
            </Button>
          )}
        </div>
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted-foreground">
            <span>
              Allocated: {mode === "percent" ? `${total}%` : `${formatAmount(total)} ${baseCurrency}`}
            </span>
            <span>
              of {mode === "percent" ? "100%" : eligible ? `${formatAmount(eligible)} ${baseCurrency}` : "—"}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className={cn("h-full transition-all", complete ? "bg-success" : "bg-warning")} style={{ width: `${pct}%` }} />
          </div>
          {error && (
            <p role="alert" className="mt-1.5 text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
