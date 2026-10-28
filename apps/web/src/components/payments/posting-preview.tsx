import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { formatAmount } from "@/lib/money";
import type { PaymentPreview } from "@/lib/types";

const FIELD_LABEL: Record<string, string> = {
  method_category_id: "Payment method",
  method_other_text: "Payment method description",
  purpose_category_id: "Purpose",
  purpose_other_text: "Purpose description",
  category_id: "Category",
  category_other_text: "Category description",
  paid_from_payment_account_id: "Paid from",
  paid_to_payment_account_id: "Paid to",
  counter_account_id: "Account",
  party_id: "Party",
  amount: "Amount",
  exchange_rate: "Exchange rate",
  received_amount: "Amount received",
  received_exchange_rate: "Received exchange rate",
  fee_amount: "Fee",
  reference_no: "Reference",
  allocations: "Employee split",
  posting_date: "Date",
};

export function fieldLabel(field: string): string {
  return FIELD_LABEL[field] ?? FIELD_LABEL[field.split(".")[0]!] ?? field;
}

/** The journal entry a payment will create, shown before submit (docs/architecture.md, Section 14.2). */
export function PostingPreview({ preview, loading }: { preview: PaymentPreview | undefined; loading: boolean }) {
  const base = preview?.base_currency ?? "USD";
  return (
    <Card aria-live="polite">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Accounting preview
          {loading && <span className="text-xs font-normal text-muted-foreground">updating…</span>}
        </CardTitle>
        <CardDescription>What will be posted to the ledger when you submit.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!preview ? (
          <p className="text-sm text-muted-foreground">Fill in the date, amount and accounts to see the entry.</p>
        ) : (
          <>
            {preview.errors.length > 0 && (
              <ul className="flex flex-col gap-1 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
                {preview.errors.map((e, i) => (
                  <li key={i} className="flex gap-2">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                    <span>
                      {e.field ? <strong>{fieldLabel(String(e.field))}: </strong> : null}
                      {String(e.message)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {preview.warnings.map((w) => (
              <p key={w} className="flex gap-2 text-sm text-muted-foreground">
                <Info className="mt-0.5 size-4 shrink-0" aria-hidden /> {w}
              </p>
            ))}
            {preview.lines.length > 0 && (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 text-left font-medium">Account</th>
                    <th className="py-1.5 text-right font-medium">Debit</th>
                    <th className="py-1.5 text-right font-medium">Credit</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {preview.lines.map((l, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1.5 pr-2">
                        <span className="font-mono text-xs text-muted-foreground">{l.account_code}</span> {l.account_name}
                        {l.currency !== base && (
                          <span className="block text-xs text-muted-foreground">
                            {formatAmount(l.amount_in_currency.replace("-", ""), 8).replace(/\.?0+$/, "")} {l.currency}
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 text-right">{Number(l.debit) ? formatAmount(l.debit) : ""}</td>
                      <td className="py-1.5 text-right">{Number(l.credit) ? formatAmount(l.credit) : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {preview.ok && (
              <p className="flex items-center gap-2 text-sm text-success">
                <CheckCircle2 className="size-4" aria-hidden /> Balanced and ready to submit
              </p>
            )}
            {preview.base_amount && (
              <p className="text-xs text-muted-foreground">
                Amounts in {base}. Payment value: {formatAmount(preview.base_amount)} {base}
                {preview.eligible_amount_base && <> · attributable revenue: {formatAmount(preview.eligible_amount_base)} {base}</>}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
