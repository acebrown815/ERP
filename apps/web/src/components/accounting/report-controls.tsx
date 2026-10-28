"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function monthRange(d = new Date()): { from: string; to: string } {
  const from = new Date(Date.UTC(d.getFullYear(), d.getMonth(), 1));
  const to = new Date(Date.UTC(d.getFullYear(), d.getMonth() + 1, 0));
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

export function yearRange(d = new Date()): { from: string; to: string } {
  return { from: `${d.getFullYear()}-01-01`, to: `${d.getFullYear()}-12-31` };
}

export function DateRange({ from, to, onChange }: { from: string; to: string; onChange: (r: { from: string; to: string }) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input aria-label="From" type="date" className="w-40" value={from} onChange={(e) => onChange({ from: e.target.value, to })} />
      <span className="text-muted-foreground">–</span>
      <Input aria-label="To" type="date" className="w-40" value={to} onChange={(e) => onChange({ from, to: e.target.value })} />
      <Button type="button" variant="ghost" size="sm" onClick={() => onChange(monthRange())}>This month</Button>
      <Button type="button" variant="ghost" size="sm" onClick={() => onChange(yearRange())}>This year</Button>
    </div>
  );
}

export function CsvButton({ path, params }: { path: string; params: Record<string, string | undefined | null> }) {
  const qs = new URLSearchParams(Object.entries({ ...params, format: "csv" }).filter(([, v]) => v) as [string, string][]);
  return (
    <Button variant="outline" asChild>
      <a href={`/api/v1${path}?${qs}`}>
        <Download /> CSV
      </a>
    </Button>
  );
}
