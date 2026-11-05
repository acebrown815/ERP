"use client";

import { useState } from "react";

import { ExportMenu } from "@/components/erp/export-menu";
import { Input, Select } from "@/components/ui/input";
import { useSalaryPeriods } from "@/lib/queries";
import { ALL_TIME_FROM, matchPreset, monthRange, rangePresets, yearRange, type PresetKey, type Range } from "@/lib/report-ranges";
import { formatDate } from "@/lib/utils";

export { ALL_TIME_FROM, monthRange, yearRange };
export type { Range };

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

/** A report's range: `initial` until someone picks another. `ready` is false while the salary periods load. */
export function useReportRange(initial: PresetKey): { range: Range; setRange: (r: Range) => void; ready: boolean } {
  const periods = useSalaryPeriods();
  const [chosen, setRange] = useState<Range | null>(null);
  const presets = rangePresets(periods.data ?? []);
  const start = presets.find((p) => p.key === initial) ?? presets.find((p) => p.key === "all_time")!;
  return { range: chosen ?? start.range, setRange, ready: !!chosen || !periods.isLoading };
}

/**
 * A time range: a preset, or any two dates from the calendar. `wholePeriods` is for reports calculated per salary
 * period, where dates inside a period still show all of it.
 */
export function DateRange({ from, to, onChange, wholePeriods }: { from: string; to: string; onChange: (r: Range) => void; wholePeriods?: boolean }) {
  const presets = rangePresets(useSalaryPeriods().data ?? []);
  const preset = matchPreset(presets, { from, to });
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Time range" className="w-40" value={preset ?? "custom"}
          onChange={(e) => {
            const picked = presets.find((p) => p.key === e.target.value);
            if (picked) onChange(picked.range);
          }}>
          {presets.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          {!preset && <option value="custom">Custom</option>}
        </Select>
        {/* Clearing a date leaves the last one in place: every report needs both ends. */}
        <Input aria-label="From" type="date" className="w-40" value={from} onChange={(e) => e.target.value && onChange({ from: e.target.value, to })} />
        <span className="text-muted-foreground">–</span>
        <Input aria-label="To" type="date" className="w-40" value={to} onChange={(e) => e.target.value && onChange({ from, to: e.target.value })} />
      </div>
      {from > to ? (
        <p role="alert" className="text-xs text-destructive">The From date is after the To date.</p>
      ) : wholePeriods && !preset ? (
        <p className="text-xs text-muted-foreground">Shows every salary period these dates touch, in full.</p>
      ) : null}
    </div>
  );
}

/** Export button for the accounting reports: CSV, Excel or PDF. */
export function CsvButton({ path, params }: { path: string; params: Record<string, string | undefined | null> }) {
  return <ExportMenu path={path} params={params} />;
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
