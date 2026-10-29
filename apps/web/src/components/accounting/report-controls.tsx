"use client";

import { ExportMenu } from "@/components/erp/export-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSalaryPeriods } from "@/lib/queries";
import { formatDate } from "@/lib/utils";

export type Range = { from: string; to: string };

export function monthRange(d = new Date()): { from: string; to: string } {
  const from = new Date(Date.UTC(d.getFullYear(), d.getMonth(), 1));
  const to = new Date(Date.UTC(d.getFullYear(), d.getMonth() + 1, 0));
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

export function yearRange(d = new Date()): { from: string; to: string } {
  return { from: `${d.getFullYear()}-01-01`, to: `${d.getFullYear()}-12-31` };
}

/**
 * "This month" for reporting = the current salary period (Settings → Salary Cycle), e.g. Oct 25 – Nov 24.
 * Falls back to the calendar month until periods have loaded.
 */
export function usePeriodRanges(): { current: Range & { label: string }; previous: (Range & { label: string }) | null; loading: boolean } {
  const periods = useSalaryPeriods();
  const list = periods.data ?? []; // newest first
  const i = list.findIndex((p) => p.is_current);
  const cur = i >= 0 ? list[i] : undefined;
  const prev = i >= 0 ? list[i + 1] : undefined;
  const asRange = (p: { start_date: string; end_date: string; label: string }) => ({ from: p.start_date, to: p.end_date, label: p.label });
  return {
    current: cur ? asRange(cur) : { ...monthRange(), label: "This month" },
    previous: prev ? asRange(prev) : null,
    loading: periods.isLoading,
  };
}

export function rangeText(r: Range): string {
  return `${formatDate(r.from)} – ${formatDate(r.to)}`;
}

export function DateRange({ from, to, onChange }: { from: string; to: string; onChange: (r: { from: string; to: string }) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input aria-label="From" type="date" className="w-40" value={from} onChange={(e) => onChange({ from: e.target.value, to })} />
      <span className="text-muted-foreground">–</span>
      <Input aria-label="To" type="date" className="w-40" value={to} onChange={(e) => onChange({ from, to: e.target.value })} />
      <PeriodButtons onChange={onChange} />
      <Button type="button" variant="ghost" size="sm" onClick={() => onChange(yearRange())}>This year</Button>
    </div>
  );
}

/** Export button for the accounting reports: CSV, Excel or PDF. */
export function CsvButton({ path, params }: { path: string; params: Record<string, string | undefined | null> }) {
  return <ExportMenu path={path} params={params} />;
}

/** Shortcuts for the current and previous salary period (the company's "month"). */
function PeriodButtons({ onChange }: { onChange: (r: Range) => void }) {
  const { current, previous } = usePeriodRanges();
  return (
    <>
      <Button type="button" variant="ghost" size="sm" title={rangeText(current)} onClick={() => onChange({ from: current.from, to: current.to })}>
        This month ({current.label})
      </Button>
      {previous && (
        <Button type="button" variant="ghost" size="sm" title={rangeText(previous)} onClick={() => onChange({ from: previous.from, to: previous.to })}>
          Last month
        </Button>
      )}
    </>
  );
}

const shiftDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/**
 * The range to compare with: the previous salary period when a period is chosen, the previous year for a
 * whole year, otherwise the same number of days just before.
 */
export function usePreviousRange(r: Range): Range & { label: string } {
  const periods = useSalaryPeriods().data ?? []; // newest first
  const i = periods.findIndex((p) => p.start_date === r.from && p.end_date === r.to);
  if (i >= 0 && periods[i + 1]) {
    const p = periods[i + 1]!;
    return { from: p.start_date, to: p.end_date, label: p.label };
  }
  const y = r.from.slice(0, 4);
  if (r.from === `${y}-01-01` && r.to === `${y}-12-31`) {
    const prev = String(Number(y) - 1);
    return { from: `${prev}-01-01`, to: `${prev}-12-31`, label: prev };
  }
  const days = Math.round((Date.parse(r.to) - Date.parse(r.from)) / 86_400_000) + 1;
  const prev = { from: shiftDays(r.from, -days), to: shiftDays(r.from, -1) };
  return { ...prev, label: rangeText(prev) };
}
