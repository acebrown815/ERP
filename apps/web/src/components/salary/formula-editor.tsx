"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { FormField } from "@/components/erp/form-field";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { formatAmount, shiftDecimal as shift, sign } from "@/lib/money";
import type { FormulaDefinition, FormulaPreview } from "@/lib/types";

import { RateChart } from "./rate-chart";
import { formatRate } from "./shared";

type Mode = FormulaDefinition["rate_schedule"]["mode"];
type Row = { a: string; b: string };
type Bonus = { label: string; min_revenue: string; amount: string };

/** Editable form of a definition: rates as percentages ("8" for 0.08), every number as a string. */
export type Draft = {
  mode: Mode;
  below: "zero" | "first_rate";
  rows: Row[]; // curve points (revenue, rate %) or tiers (from revenue, rate %)
  fixed: string;
  bonuses: Bonus[];
  min: string;
  max: string;
};

const EXAMPLES = ["2999.99", "3000", "6000", "10000", "20000", "30000", "40000"];

export function toDraft(d: FormulaDefinition): Draft {
  const s = d.rate_schedule;
  const rows =
    s.mode === "linear_curve"
      ? (s.points ?? []).map((p) => ({ a: shift(String(p.revenue), 0), b: shift(String(p.rate), 2) }))
      : (s.tiers ?? []).map((t) => ({ a: shift(String(t.from_revenue), 0), b: shift(String(t.rate), 2) }));
  return {
    mode: s.mode,
    below: s.below_first_point ?? "zero",
    rows,
    fixed: sign(String(d.fixed_amount ?? "0")) ? shift(String(d.fixed_amount), 0) : "",
    bonuses: (d.bonuses ?? []).map((b) => ({ label: b.label, min_revenue: shift(String(b.min_revenue), 0), amount: shift(String(b.amount), 0) })),
    min: d.min_payout != null ? shift(String(d.min_payout), 0) : "",
    max: d.max_payout != null ? shift(String(d.max_payout), 0) : "",
  };
}

export function fromDraft(d: Draft): FormulaDefinition {
  const rows = d.rows.filter((r) => r.a.trim() !== "" || r.b.trim() !== "");
  return {
    rate_schedule: {
      mode: d.mode,
      below_first_point: d.below,
      points: d.mode === "linear_curve" ? rows.map((r) => ({ revenue: r.a.trim(), rate: shift(r.b, -2) })) : [],
      tiers: d.mode === "flat_tiers" || d.mode === "progressive_tiers" ? rows.map((r) => ({ from_revenue: r.a.trim(), rate: shift(r.b, -2) })) : [],
    },
    fixed_amount: d.fixed.trim() || "0",
    bonuses: d.bonuses.filter((b) => b.label.trim()).map((b) => ({ label: b.label.trim(), min_revenue: b.min_revenue.trim() || "0", amount: b.amount.trim() || "0" })),
    min_payout: d.min.trim() || null,
    max_payout: d.max.trim() || null,
    rounding: { mode: "half_up", precision: 2 },
  } as FormulaDefinition;
}

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "linear_curve", label: "Rate curve", hint: "The rate rises in straight lines between the points and applies to the whole revenue." },
  { value: "flat_tiers", label: "Flat tiers", hint: "The tier the revenue falls in sets the rate for the whole revenue." },
  { value: "progressive_tiers", label: "Progressive tiers", hint: "Each slice of revenue is paid at its own tier's rate, like tax bands." },
  { value: "none", label: "No revenue share", hint: "Fixed amount and bonuses only." },
];

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function FormulaEditor({ value, onChange, readOnly = false }: { value: Draft; onChange: (d: Draft) => void; readOnly?: boolean }) {
  const definition = useDebounced(fromDraft(value));
  const preview = useQuery({
    queryKey: ["formula-preview", definition],
    queryFn: () => api.post<FormulaPreview>("/comp-formulas/preview", { definition, revenues: EXAMPLES }),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const set = (patch: Partial<Draft>) => onChange({ ...value, ...patch });
  const setRow = (i: number, patch: Partial<Row>) => set({ rows: value.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const setBonus = (i: number, patch: Partial<Bonus>) => set({ bonuses: value.bonuses.map((b, j) => (j === i ? { ...b, ...patch } : b)) });
  const curve = value.mode === "linear_curve";
  const error = preview.error instanceof ApiError ? preview.error : null;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,26rem)_1fr]">
      <fieldset disabled={readOnly} className="flex min-w-0 flex-col gap-4">
        <FormField id="f_mode" label="How revenue is paid" hint={MODES.find((m) => m.value === value.mode)?.hint}>
          <Select id="f_mode" value={value.mode} onChange={(e) => {
            const mode = e.target.value as Mode;
            const rows = value.rows.length || mode === "none" ? value.rows : [{ a: "0", b: "" }];
            set({ mode, rows });
          }}>
            {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </Select>
        </FormField>

        {value.mode !== "none" && (
          <div className="flex flex-col gap-2">
            <Table>
              <THead>
                <TR>
                  <TH>{curve ? "Monthly revenue" : "From revenue"}</TH>
                  <TH className="w-28">Rate %</TH>
                  {!readOnly && <TH className="w-10"><span className="sr-only">Remove</span></TH>}
                </TR>
              </THead>
              <TBody>
                {value.rows.map((r, i) => (
                  <TR key={i}>
                    <TD><Input aria-label={`Revenue, row ${i + 1}`} inputMode="decimal" value={r.a} onChange={(e) => setRow(i, { a: e.target.value })} /></TD>
                    <TD><Input aria-label={`Rate percent, row ${i + 1}`} inputMode="decimal" value={r.b} onChange={(e) => setRow(i, { b: e.target.value })} /></TD>
                    {!readOnly && (
                      <TD>
                        <Button type="button" variant="ghost" size="icon" aria-label={`Remove row ${i + 1}`} onClick={() => set({ rows: value.rows.filter((_, j) => j !== i) })}>
                          <Trash2 />
                        </Button>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
            {!readOnly && (
              <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => set({ rows: [...value.rows, { a: "", b: "" }] })}>
                <Plus /> Add {curve ? "point" : "tier"}
              </Button>
            )}
            {curve && (
              <FormField id="f_below" label="Below the first point">
                <Select id="f_below" value={value.below} onChange={(e) => set({ below: e.target.value as Draft["below"] })}>
                  <option value="zero">No salary</option>
                  <option value="first_rate">Pay the first point&apos;s rate</option>
                </Select>
              </FormField>
            )}
            {curve && <p className="text-xs text-muted-foreground">Above the last point the last rate holds.</p>}
          </div>
        )}

        <div className="grid grid-cols-3 gap-3">
          <FormField id="f_fixed" label="Fixed / month"><Input id="f_fixed" inputMode="decimal" placeholder="0" value={value.fixed} onChange={(e) => set({ fixed: e.target.value })} /></FormField>
          <FormField id="f_min" label="Minimum"><Input id="f_min" inputMode="decimal" placeholder="none" value={value.min} onChange={(e) => set({ min: e.target.value })} /></FormField>
          <FormField id="f_max" label="Maximum"><Input id="f_max" inputMode="decimal" placeholder="none" value={value.max} onChange={(e) => set({ max: e.target.value })} /></FormField>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">Bonuses</p>
          {value.bonuses.length === 0 && <p className="text-xs text-muted-foreground">None. A bonus pays a fixed amount when monthly revenue reaches a threshold.</p>}
          {value.bonuses.map((b, i) => (
            <div key={i} className="grid grid-cols-[1fr_7rem_6rem_auto] items-center gap-2">
              <Input aria-label={`Bonus ${i + 1} name`} placeholder="e.g. Big month" value={b.label} onChange={(e) => setBonus(i, { label: e.target.value })} />
              <Input aria-label={`Bonus ${i + 1} revenue threshold`} inputMode="decimal" placeholder="at revenue" value={b.min_revenue} onChange={(e) => setBonus(i, { min_revenue: e.target.value })} />
              <Input aria-label={`Bonus ${i + 1} amount`} inputMode="decimal" placeholder="amount" value={b.amount} onChange={(e) => setBonus(i, { amount: e.target.value })} />
              {!readOnly && (
                <Button type="button" variant="ghost" size="icon" aria-label={`Remove bonus ${i + 1}`} onClick={() => set({ bonuses: value.bonuses.filter((_, j) => j !== i) })}><Trash2 /></Button>
              )}
            </div>
          ))}
          {!readOnly && (
            <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => set({ bonuses: [...value.bonuses, { label: "", min_revenue: "", amount: "" }] })}>
              <Plus /> Add bonus
            </Button>
          )}
        </div>
      </fieldset>

      <div className="flex min-w-0 flex-col gap-4">
        {error ? (
          <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            {error.errors.length ? error.errors.map((e, i) => <p key={i}>{e.message}</p>) : error.message}
          </div>
        ) : preview.data ? (
          <>
            <RateChart points={preview.data.chart} />
            <Table>
              <THead><TR><TH>Monthly revenue</TH><TH className="text-right">Rate</TH><TH className="text-right">Salary</TH></TR></THead>
              <TBody>
                {preview.data.rows.map((r) => (
                  <TR key={r.revenue}>
                    <TD className="tabular">{formatAmount(r.revenue)}</TD>
                    <TD className="tabular text-right">{formatRate(r.rate)}</TD>
                    <TD className="tabular text-right font-medium">{formatAmount(r.amount)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Calculating…</p>
        )}
      </div>
    </div>
  );
}
