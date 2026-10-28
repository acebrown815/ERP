"use client";

import { useState } from "react";

import { formatAmount } from "@/lib/money";
import type { FormulaPreview } from "@/lib/types";

import { formatRate } from "./shared";

const W = 640;
const H = 240;
const PAD = { top: 12, right: 56, bottom: 28, left: 64 };

function ticks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  return Array.from({ length: Math.floor(max / step) + 1 }, (_, i) => i * step);
}

const compact = (n: number) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);

/**
 * Salary (solid, left axis) and rate (dashed, right axis) against monthly revenue. Chart values are
 * display-only floats; the numbers in tables come from the server as exact decimals.
 */
export function RateChart({ points, currency = "USD" }: { points: FormulaPreview["chart"]; currency?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;
  const data = points.map((p) => ({ x: Number(p.revenue), amount: Number(p.amount), rate: Number(p.rate) }));
  const xMax = Math.max(...data.map((d) => d.x)) || 1;
  const yMax = Math.max(...data.map((d) => d.amount), 1) * 1.08;
  const rMax = Math.max(...data.map((d) => d.rate), 0.01) * 1.08;
  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const sx = (x: number) => PAD.left + (x / xMax) * iw;
  const sy = (y: number) => PAD.top + ih - (y / yMax) * ih;
  const sr = (r: number) => PAD.top + ih - (r / rMax) * ih;
  const path = (f: (d: (typeof data)[number]) => number) => data.map((d, i) => `${i ? "L" : "M"}${sx(d.x).toFixed(1)},${f(d).toFixed(1)}`).join("");
  const h = hover !== null ? data[hover] : undefined;

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * W;
    const rev = ((x - PAD.left) / iw) * xMax;
    let best = 0;
    data.forEach((d, i) => {
      if (Math.abs(d.x - rev) < Math.abs(data[best]!.x - rev)) best = i;
    });
    setHover(best);
  };

  return (
    <figure className="flex flex-col gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full touch-none select-none" role="img"
        aria-label="Salary and rate by monthly revenue" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {ticks(yMax).map((t) => (
          <g key={`y${t}`}>
            <line x1={PAD.left} x2={W - PAD.right} y1={sy(t)} y2={sy(t)} stroke="var(--border)" />
            <text x={PAD.left - 8} y={sy(t)} textAnchor="end" dominantBaseline="middle" className="fill-muted-foreground text-[11px]">{compact(t)}</text>
          </g>
        ))}
        {ticks(rMax * 100).map((t) => (
          <text key={`r${t}`} x={W - PAD.right + 8} y={sr(t / 100)} dominantBaseline="middle" className="fill-muted-foreground text-[11px]">{t}%</text>
        ))}
        {ticks(xMax, 5).map((t) => (
          <text key={`x${t}`} x={sx(t)} y={H - 8} textAnchor="middle" className="fill-muted-foreground text-[11px]">{compact(t)}</text>
        ))}
        <path d={path((d) => sr(d.rate))} fill="none" stroke="var(--warning)" strokeWidth={2} strokeDasharray="5 4" />
        <path d={path((d) => sy(d.amount))} fill="none" stroke="var(--primary)" strokeWidth={2.5} />
        {h && (
          <g>
            <line x1={sx(h.x)} x2={sx(h.x)} y1={PAD.top} y2={PAD.top + ih} stroke="var(--muted-foreground)" strokeDasharray="2 3" />
            <circle cx={sx(h.x)} cy={sy(h.amount)} r={4} fill="var(--primary)" />
            <circle cx={sx(h.x)} cy={sr(h.rate)} r={3.5} fill="var(--warning)" />
          </g>
        )}
      </svg>
      <figcaption className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 rounded bg-primary" /> Salary ({currency}, left)</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 rounded border-t-2 border-dashed border-warning" /> Rate (right)</span>
        <span className="tabular ml-auto text-foreground">
          {h ? <>Revenue {formatAmount(points[hover!]!.revenue)} → rate {formatRate(points[hover!]!.rate)} → salary {formatAmount(points[hover!]!.amount)}</> : "Hover the chart to read values"}
        </span>
      </figcaption>
    </figure>
  );
}
