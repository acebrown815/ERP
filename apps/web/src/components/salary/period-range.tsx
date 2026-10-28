"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Label } from "@/components/ui/misc";
import type { SalaryPeriod } from "@/lib/types";

export type Range = { from?: string; to?: string };

/** From/to salary period pickers plus CSV download. Empty range = the last six periods. */
export function PeriodRange({ periods, value, onChange, csvPath }: { periods: SalaryPeriod[]; value: Range; onChange: (r: Range) => void; csvPath: string }) {
  const started = periods.filter((p) => !p.is_future);
  const query = new URLSearchParams({ format: "csv", ...(value.from && value.to ? { from_period_id: value.from, to_period_id: value.to } : {}) });
  const pick = (key: "from" | "to") => (
    <Select id={`range_${key}`} className="w-auto" value={value[key] ?? ""} onChange={(e) => onChange({ ...value, [key]: e.target.value || undefined })}>
      <option value="">{key === "from" ? "Last 6 periods" : "Current"}</option>
      {started.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
    </Select>
  );
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex flex-col gap-1"><Label htmlFor="range_from">From</Label>{pick("from")}</div>
      <div className="flex flex-col gap-1"><Label htmlFor="range_to">To</Label>{pick("to")}</div>
      <Button variant="outline" asChild><a href={`/api/v1${csvPath}?${query}`}><Download /> CSV</a></Button>
    </div>
  );
}

/** Both ends chosen, or neither (server default). */
export function rangeQuery(r: Range): Record<string, string | undefined> {
  return r.from && r.to ? { from_period_id: r.from, to_period_id: r.to } : {};
}
