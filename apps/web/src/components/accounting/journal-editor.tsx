"use client";

import { Plus, Trash2 } from "lucide-react";

import { AccountPicker } from "@/components/erp/pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatAmount, isDecimal, sum } from "@/lib/money";
import { useAccounts, useCompany } from "@/lib/queries";
import { cn } from "@/lib/utils";

export type DraftLine = {
  key: string;
  account_id: string | null;
  debit: string;
  credit: string;
  amount_in_currency: string;
  exchange_rate: string;
  description: string;
};

let n = 0;
export const newLine = (): DraftLine => ({
  key: `l${++n}`,
  account_id: null,
  debit: "",
  credit: "",
  amount_in_currency: "",
  exchange_rate: "",
  description: "",
});

export function toLineBody(l: DraftLine, foreign: boolean) {
  const signed = l.debit ? l.amount_in_currency : l.amount_in_currency ? `-${l.amount_in_currency.replace("-", "")}` : "";
  return {
    account_id: l.account_id,
    debit: l.debit || "0",
    credit: l.credit || "0",
    amount_in_currency: foreign && signed ? signed : null,
    exchange_rate: foreign && l.exchange_rate ? l.exchange_rate : null,
    description: l.description || null,
  };
}

/** Debit/credit grid with running totals. `allowUnbalanced` is for opening balances (auto-offset). */
export function JournalLinesEditor({
  lines,
  onChange,
  allowUnbalanced = false,
  errors = {},
}: {
  lines: DraftLine[];
  onChange: (lines: DraftLine[]) => void;
  allowUnbalanced?: boolean;
  errors?: Record<string, string>;
}) {
  const accounts = useAccounts();
  const base = useCompany().data?.base_currency ?? "USD";
  const totalDebit = sum(lines.map((l) => l.debit));
  const totalCredit = sum(lines.map((l) => l.credit));
  const diff = sum([totalDebit, `-${totalCredit}`]);
  const update = (key: string, patch: Partial<DraftLine>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const currencyOf = (id: string | null) => accounts.data?.find((a) => a.id === id)?.currency;

  return (
    <div className="flex flex-col gap-2">
      <div className="hidden grid-cols-[minmax(0,1fr)_8rem_8rem_2.25rem] gap-2 px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground md:grid">
        <span>Account</span>
        <span className="text-right">Debit ({base})</span>
        <span className="text-right">Credit ({base})</span>
        <span />
      </div>
      {lines.map((l, i) => {
        const cur = currencyOf(l.account_id);
        const foreign = !!cur && cur !== base;
        const err = errors[`lines.${i}`] ?? errors[`lines.${i}.account_id`] ?? errors[`lines.${i}.amount_in_currency`];
        return (
          <div key={l.key} className="rounded-md border p-2 md:border-0 md:p-0">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-[minmax(0,1fr)_8rem_8rem_2.25rem]">
              <div className="col-span-2 md:col-span-1">
                <AccountPicker id={`line-${i}`} value={l.account_id} onChange={(v) => update(l.key, { account_id: v })} invalid={!!err} />
              </div>
              <Input aria-label="Debit" inputMode="decimal" className="tabular text-right" value={l.debit}
                onChange={(e) => update(l.key, { debit: e.target.value.trim(), credit: e.target.value.trim() ? "" : l.credit })} />
              <Input aria-label="Credit" inputMode="decimal" className="tabular text-right" value={l.credit}
                onChange={(e) => update(l.key, { credit: e.target.value.trim(), debit: e.target.value.trim() ? "" : l.debit })} />
              <Button type="button" variant="ghost" size="icon" aria-label="Remove line" className="hidden md:inline-flex"
                onClick={() => onChange(lines.filter((x) => x.key !== l.key))}>
                <Trash2 />
              </Button>
            </div>
            {foreign && (
              <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-[minmax(0,1fr)_8rem_8rem_2.25rem]">
                <span className="self-center text-xs text-muted-foreground">This account is in {cur}</span>
                <Input aria-label={`Amount in ${cur}`} placeholder={`${cur} amount`} inputMode="decimal" className="tabular text-right"
                  value={l.amount_in_currency} onChange={(e) => update(l.key, { amount_in_currency: e.target.value.trim() })} />
                <Input aria-label="Rate" placeholder={`1 ${cur} = ? ${base}`} inputMode="decimal" className="tabular text-right"
                  value={l.exchange_rate} onChange={(e) => update(l.key, { exchange_rate: e.target.value.trim() })} />
              </div>
            )}
            {err && <p role="alert" className="mt-1 text-xs text-destructive">{err}</p>}
          </div>
        );
      })}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2">
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...lines, newLine()])}>
          <Plus /> Add line
        </Button>
        <div className="tabular flex gap-6 text-sm">
          <span>Debit {formatAmount(totalDebit)}</span>
          <span>Credit {formatAmount(totalCredit)}</span>
          <span className={cn(diff === "0" ? "text-success" : allowUnbalanced ? "text-muted-foreground" : "text-destructive")}>
            {diff === "0" ? "Balanced" : allowUnbalanced ? `Offset to Opening Balance Equity: ${formatAmount(diff.replace("-", ""))}` : `Off by ${formatAmount(diff.replace("-", ""))}`}
          </span>
        </div>
      </div>
    </div>
  );
}

export function linesValid(lines: DraftLine[]): boolean {
  return lines.every((l) => l.account_id && ((l.debit && isDecimal(l.debit)) || (l.credit && isDecimal(l.credit))));
}
