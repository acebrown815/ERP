"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { ReactNode } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, Skeleton } from "@/components/ui/misc";
import { formatAmount } from "@/lib/money";
import { cn } from "@/lib/utils";

/** Categorical slots, always assigned in this order (globals.css: --chart-1..4). */
export const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"] as const;

export type Series = { key: string; label: string; color: string; stack?: string };
export type Row = Record<string, string | number | null>;

/** Display only: amounts arrive as decimal strings. */
export const num = (v: string | number | null | undefined): number => (v === null || v === undefined || v === "" ? 0 : Number(v));

/** 12,500 → "12.5k"; for axis ticks only. */
export function compact(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k`;
  return String(Math.round(n));
}

export function Legend({ series }: { series: { label: string; color: string; line?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {series.map((s) => (
        <li key={s.label} className="flex items-center gap-1.5">
          <span className={s.line ? "h-0.5 w-3 rounded-full" : "size-2.5 rounded-sm"} style={{ background: s.color }} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

type TipItem = { name?: string | number; value?: unknown; color?: string; dataKey?: unknown };

function TooltipBox({ active, payload, label, unit }: { active?: boolean; payload?: readonly TipItem[]; label?: string | number; unit?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-card px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-foreground">{label}</p>
      <ul className="flex flex-col gap-0.5">
        {payload.map((p) => (
          <li key={String(p.dataKey)} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2 rounded-sm" style={{ background: p.color }} aria-hidden />
              {p.name}
            </span>
            <span className="tabular text-foreground">{formatAmount(String(p.value ?? 0))}{unit ? ` ${unit}` : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const axis = { stroke: "var(--chart-axis)", fontSize: 11, tickLine: false } as const;

/** Bars per period (grouped, or stacked when series share `stack`), with an optional line on the same scale. */
export function PeriodChart({
  data,
  xKey = "label",
  bars,
  line,
  height = 260,
  unit,
  label,
}: {
  data: Row[];
  xKey?: string;
  bars: Series[];
  line?: Series;
  height?: number;
  unit?: string;
  label: string;
}) {
  return (
    <figure className="flex flex-col gap-2" aria-label={label}>
      <Legend series={[...bars, ...(line ? [{ ...line, line: true }] : [])]} />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="24%">
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey={xKey} {...axis} axisLine={{ stroke: "var(--chart-grid)" }} interval="preserveStartEnd" minTickGap={8} />
            <YAxis {...axis} axisLine={false} width={44} tickFormatter={(v: number) => compact(v)} />
            <ReferenceLine y={0} stroke="var(--chart-axis)" strokeOpacity={0.5} />
            <Tooltip content={(p) => <TooltipBox {...p} unit={unit} />} cursor={{ fill: "var(--muted)", opacity: 0.6 }} />
            {bars.map((b) => (
              <Bar key={b.key} dataKey={b.key} name={b.label} fill={b.color} stackId={b.stack} radius={b.stack ? 0 : [4, 4, 0, 0]} maxBarSize={28} />
            ))}
            {line && (
              <Line dataKey={line.key} name={line.label} stroke={line.color} strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: line.color }} activeDot={{ r: 5 }} type="monotone" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/** One or more lines over periods. */
export function TrendChart({ data, xKey = "label", lines, height = 240, unit, label }: { data: Row[]; xKey?: string; lines: Series[]; height?: number; unit?: string; label: string }) {
  return (
    <figure className="flex flex-col gap-2" aria-label={label}>
      {lines.length > 1 && <Legend series={lines.map((l) => ({ ...l, line: true }))} />}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey={xKey} {...axis} axisLine={{ stroke: "var(--chart-grid)" }} interval="preserveStartEnd" minTickGap={8} />
            <YAxis {...axis} axisLine={false} width={44} tickFormatter={(v: number) => compact(v)} />
            <ReferenceLine y={0} stroke="var(--chart-axis)" strokeOpacity={0.5} />
            <Tooltip content={(p) => <TooltipBox {...p} unit={unit} />} cursor={{ stroke: "var(--chart-axis)", strokeDasharray: "3 3" }} />
            {lines.map((l) => (
              <Line key={l.key} dataKey={l.key} name={l.label} stroke={l.color} strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: l.color }} activeDot={{ r: 5 }} type="monotone" />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/** Tiny trend line for stat tiles: no axes, no tooltip. */
export function Sparkline({ values, color = SERIES[0], label }: { values: number[]; color?: string; label: string }) {
  if (values.length < 2) return null;
  const data = values.map((v, i) => ({ i, v }));
  return (
    <div className="h-8 w-24" role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 3, right: 3, bottom: 3, left: 3 }}>
          <Line dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} type="monotone" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Change vs a previous value: arrow + %. `goodWhenUp=false` for costs (a rise is bad). */
export function Delta({ current, previous, goodWhenUp = true, suffix = "vs last month" }: { current: number; previous: number | null | undefined; goodWhenUp?: boolean; suffix?: string }) {
  if (previous === null || previous === undefined) return null;
  const diff = current - previous;
  if (previous === 0 && diff === 0) return <span className="text-xs text-muted-foreground">No change {suffix}</span>;
  const pct = previous !== 0 ? (diff / Math.abs(previous)) * 100 : null;
  const up = diff > 0;
  const good = diff === 0 ? null : up === goodWhenUp;
  const Icon = diff === 0 ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs", good === true && "text-success", good === false && "text-destructive", good === null && "text-muted-foreground")}>
      <Icon className="size-3.5" aria-hidden />
      <span className="tabular">{pct === null ? "new" : `${up ? "+" : ""}${pct.toFixed(Math.abs(pct) < 10 ? 1 : 0)}%`}</span>
      <span className="text-muted-foreground">{suffix}</span>
    </span>
  );
}

/** A headline number with an optional change line and sparkline. */
export function StatTile({
  label,
  value,
  unit,
  hint,
  delta,
  spark,
  tone,
  children,
}: {
  label: string;
  value: ReactNode | undefined;
  unit?: string;
  hint?: ReactNode;
  delta?: ReactNode;
  spark?: ReactNode;
  tone?: "good" | "bad";
  children?: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-2 py-4">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          {value === undefined ? <Skeleton className="mt-1 h-8 w-32" /> : (
            <p className={cn("mt-1 text-2xl font-semibold", tone === "bad" && "text-destructive", tone === "good" && "text-success")}>
              {value}{unit && <span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span>}
            </p>
          )}
          {delta && <div className="mt-0.5">{delta}</div>}
          {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
          {children}
        </div>
        {spark}
      </CardContent>
    </Card>
  );
}
