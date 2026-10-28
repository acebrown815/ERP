"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Save, Send, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { CategorySelect, useCategories, type CategoryValue } from "@/components/erp/category-select";
import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { AccountPicker, PartyPicker, PaymentAccountPicker, ProjectPicker, EmployeePicker } from "@/components/erp/pickers";
import { AllocationEditor, newSplitRow, type SplitDraft, type SplitMode } from "@/components/payments/allocation-editor";
import { fieldLabel, PostingPreview } from "@/components/payments/posting-preview";
import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { decimals, formatAmount, isDecimal } from "@/lib/money";
import { currencyPrecision, useCompany, useCurrencies, useEmployees, usePaymentAccounts } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { PaymentEntry, PaymentPreview, SplitRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type Direction = "receive" | "pay" | "internal_transfer";

type FormState = {
  posting_date: string;
  direction: Direction;
  party_id: string | null;
  method: CategoryValue;
  purpose: CategoryValue;
  category: CategoryValue;
  paid_from_payment_account_id: string | null;
  paid_to_payment_account_id: string | null;
  counter_account_id: string | null;
  amount: string;
  exchange_rate: string;
  received_amount: string;
  received_exchange_rate: string;
  fee_amount: string;
  fee_paid_by: "client" | "company";
  project_id: string | null;
  employee_id: string | null;
  reference_no: string;
  description: string;
};

const today = () => new Date().toISOString().slice(0, 10);
const emptyCat = (): CategoryValue => ({ category_id: null, other_text: "" });

function fromEntry(e: PaymentEntry): FormState {
  return {
    posting_date: e.posting_date,
    direction: e.direction as Direction,
    party_id: e.party_id ?? null,
    method: { category_id: e.method_category_id ?? null, other_text: e.method_other_text ?? "" },
    purpose: { category_id: e.purpose_category_id ?? null, other_text: e.purpose_other_text ?? "" },
    category: { category_id: e.category_id ?? null, other_text: e.category_other_text ?? "" },
    paid_from_payment_account_id: e.paid_from_payment_account_id ?? null,
    paid_to_payment_account_id: e.paid_to_payment_account_id ?? null,
    counter_account_id: e.counter_account_id ?? null,
    amount: trimZeros(e.amount),
    exchange_rate: trimZeros(e.exchange_rate),
    received_amount: e.received_amount ? trimZeros(e.received_amount) : "",
    received_exchange_rate: e.received_exchange_rate ? trimZeros(e.received_exchange_rate) : "",
    fee_amount: Number(e.fee_amount) ? trimZeros(e.fee_amount) : "",
    fee_paid_by: e.fee_paid_by as "client" | "company",
    project_id: e.project_id ?? null,
    employee_id: e.employee_id ?? null,
    reference_no: e.reference_no ?? "",
    description: e.description ?? "",
  };
}

function trimZeros(v: string): string {
  return v.includes(".") ? v.replace(/0+$/, "").replace(/\.$/, "") : v;
}

const blank = (direction: Direction): FormState => ({
  posting_date: today(),
  direction,
  party_id: null,
  method: emptyCat(),
  purpose: emptyCat(),
  category: emptyCat(),
  paid_from_payment_account_id: null,
  paid_to_payment_account_id: null,
  counter_account_id: null,
  amount: "",
  exchange_rate: "1",
  received_amount: "",
  received_exchange_rate: "",
  fee_amount: "",
  fee_paid_by: "company",
  project_id: null,
  employee_id: null,
  reference_no: "",
  description: "",
});

function toBody(f: FormState, splits: SplitRow[] | null) {
  const transfer = f.direction === "internal_transfer";
  return {
    posting_date: f.posting_date,
    direction: f.direction,
    party_id: transfer ? null : f.party_id,
    method_category_id: f.method.category_id,
    method_other_text: f.method.other_text || null,
    purpose_category_id: f.purpose.category_id,
    purpose_other_text: f.purpose.other_text || null,
    category_id: transfer ? null : f.category.category_id,
    category_other_text: transfer ? null : f.category.other_text || null,
    paid_from_payment_account_id: f.direction === "receive" ? null : f.paid_from_payment_account_id,
    paid_to_payment_account_id: f.direction === "pay" ? null : f.paid_to_payment_account_id,
    counter_account_id: transfer ? null : f.counter_account_id,
    amount: f.amount,
    exchange_rate: f.exchange_rate || "1",
    received_amount: transfer && f.received_amount ? f.received_amount : null,
    received_exchange_rate: transfer && f.received_exchange_rate ? f.received_exchange_rate : null,
    fee_amount: f.fee_amount || "0",
    fee_paid_by: f.fee_paid_by,
    project_id: transfer ? null : f.project_id,
    employee_id: f.direction === "pay" ? f.employee_id : null,
    reference_no: f.reference_no || null,
    description: f.description || null,
    allocations: splits,
  };
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

const DIRECTIONS: { value: Direction; label: string; icon: typeof ArrowDownLeft; hint: string }[] = [
  { value: "receive", label: "Receive", icon: ArrowDownLeft, hint: "Money came in" },
  { value: "pay", label: "Pay", icon: ArrowUpRight, hint: "Money went out" },
  { value: "internal_transfer", label: "Transfer", icon: ArrowLeftRight, hint: "Between our accounts" },
];

export function PaymentEntryEditor({ entry }: { entry?: PaymentEntry }) {
  const router = useRouter();
  const qc = useQueryClient();
  const can = useCan();
  const company = useCompany();
  const currencies = useCurrencies();
  const paymentAccounts = usePaymentAccounts();
  const purposes = useCategories("payment_purpose");
  const base = company.data?.base_currency ?? "USD";

  const [form, setForm] = useState<FormState>(() => (entry ? fromEntry(entry) : blank("receive")));
  const [mode, setMode] = useState<SplitMode>(() => (entry?.allocations[0]?.method === "amount" ? "amount" : "percent"));
  const [splits, setSplits] = useState<SplitDraft[]>(() =>
    (entry?.allocations ?? []).map((a) =>
      newSplitRow(a.employee_id, trimZeros((a.method === "amount" ? a.amount : a.percent) ?? "")),
    ),
  );
  const [splitTouched, setSplitTouched] = useState(!!entry?.allocations.length);
  const [rateTouched, setRateTouched] = useState(!!entry);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));

  const ours = paymentAccounts.data?.find(
    (p) => p.id === (form.direction === "receive" ? form.paid_to_payment_account_id : form.paid_from_payment_account_id),
  );
  const dst = paymentAccounts.data?.find((p) => p.id === form.paid_to_payment_account_id);
  const currency = ours?.currency ?? base;
  const precision = currencyPrecision(currencies.data, currency);
  const purpose = purposes.data?.find((c) => c.id === form.purpose.category_id);
  const requiresSplit = !!purpose?.config?.requires_attribution;
  const isTransfer = form.direction === "internal_transfer";
  const crossCurrency = isTransfer && dst && ours && dst.currency !== ours.currency;

  // Exchange rates: fetch the stored rate for the date unless the user typed one.
  const rateLookup = useQuery({
    queryKey: ["rate", currency, base, form.posting_date],
    queryFn: () => api.get<{ rate: string }>("/exchange-rates/lookup", { from: currency, to: base, on: form.posting_date }),
    enabled: currency !== base && !!form.posting_date,
    retry: false,
  });
  useEffect(() => {
    if (currency === base) set("exchange_rate", "1");
    else if (!rateTouched && rateLookup.data) set("exchange_rate", trimZeros(rateLookup.data.rate));
  }, [currency, base, rateLookup.data, rateTouched]);
  const dstRateLookup = useQuery({
    queryKey: ["rate", dst?.currency, base, form.posting_date],
    queryFn: () => api.get<{ rate: string }>("/exchange-rates/lookup", { from: dst!.currency, to: base, on: form.posting_date }),
    enabled: !!crossCurrency && dst?.currency !== base,
    retry: false,
  });
  useEffect(() => {
    if (!crossCurrency) return;
    if (dst?.currency === base) set("received_exchange_rate", "1");
    else if (dstRateLookup.data && !form.received_exchange_rate) set("received_exchange_rate", trimZeros(dstRateLookup.data.rate));
  }, [crossCurrency, dst?.currency, base, dstRateLookup.data, form.received_exchange_rate]);

  // Pre-fill the split from the project's default when the user hasn't edited it.
  const loadProjectDefault = async (projectId: string | null) => {
    if (!projectId) return;
    const rows = await api.get<SplitRow[]>("/payment-entries/proposal", { project_id: projectId });
    setMode("percent");
    setSplits(rows.map((r) => newSplitRow(r.employee_id, trimZeros(String(r.percent ?? "")))));
  };
  useEffect(() => {
    if (!splitTouched && requiresSplit && form.project_id) void loadProjectDefault(form.project_id);
  }, [form.project_id, requiresSplit, splitTouched]);

  const splitRows: SplitRow[] | null = requiresSplit
    ? splits
        .filter((s) => s.employee_id && isDecimal(s.value) && Number(s.value) > 0)
        .map((s) => ({
          employee_id: s.employee_id!,
          percent: mode === "percent" ? s.value : null,
          amount: mode === "amount" ? s.value : null,
          project_id: form.project_id,
        }))
    : null;

  const amountError =
    form.amount && (!isDecimal(form.amount) || Number(form.amount) <= 0)
      ? "Enter a positive number"
      : form.amount && decimals(form.amount) > precision
        ? `${currency} allows ${precision} decimal places`
        : undefined;
  const body = useMemo(() => toBody(form, splitRows), [form, JSON.stringify(splitRows)]); // eslint-disable-line react-hooks/exhaustive-deps
  const debounced = useDebounced(body, 400);
  const previewable = !!debounced.amount && isDecimal(debounced.amount) && Number(debounced.amount) > 0 && !amountError;
  const preview = useQuery({
    queryKey: ["payment-preview", debounced],
    queryFn: () => api.post<PaymentPreview>("/payment-entries/preview", debounced),
    enabled: previewable,
    placeholderData: (prev) => prev,
    retry: false,
  });
  const errors = useMemo(() => {
    const out: Record<string, string> = { ...serverErrors };
    for (const e of preview.data?.errors ?? []) if (e.field && !out[String(e.field)]) out[String(e.field)] = String(e.message);
    return out;
  }, [preview.data, serverErrors]);

  const save = useMutation({
    mutationFn: async (): Promise<PaymentEntry> => {
      setServerErrors({});
      if (entry) return api.patch<PaymentEntry>(`/payment-entries/${entry.id}`, { ...body, version: entry.version });
      return api.post<PaymentEntry>("/payment-entries", body, { idempotencyKey: newIdempotencyKey() });
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setServerErrors(err.fieldErrors());
        toast.error(err.status === 412 ? "Someone else changed this payment. Reload to see the latest." : err.message);
      }
    },
  });

  const onSave = async () => {
    const saved = await save.mutateAsync();
    qc.invalidateQueries({ queryKey: ["payment-entries"] });
    toast.success(`Draft ${saved.number} saved`);
    if (!entry) router.replace(`/accounting/payment-entries/${saved.id}`);
    else qc.setQueryData(["payment-entry", saved.id], saved);
  };

  const onSubmit = async () => {
    try {
      const saved = await save.mutateAsync();
      const done = await api.post<PaymentEntry>(`/payment-entries/${saved.id}/submit`, undefined, {
        idempotencyKey: newIdempotencyKey(),
      });
      qc.invalidateQueries({ queryKey: ["payment-entries"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.setQueryData(["payment-entry", done.id], done);
      toast.success(`${done.number} submitted and posted to the ledger`);
      router.replace(`/accounting/payment-entries/${done.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setServerErrors(err.fieldErrors());
        toast.error(err.message);
      }
      throw err;
    }
  };

  const setDirection = (d: Direction) =>
    setForm((f) => ({ ...blank(d), posting_date: f.posting_date, amount: f.amount, description: f.description }));

  const canSubmit = can("payments.submit");
  const ready = preview.data?.ok && !preview.isFetching;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <form
        className="flex flex-col gap-6"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void onSave();
        }}
      >
        <Card>
          <CardHeader>
            <CardTitle>Payment</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div role="radiogroup" aria-label="Direction" className="grid grid-cols-3 gap-2">
              {DIRECTIONS.map((d) => (
                <button
                  key={d.value}
                  type="button"
                  role="radio"
                  aria-checked={form.direction === d.value}
                  onClick={() => setDirection(d.value)}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-md border px-2 py-3 text-sm transition-colors hover:bg-muted",
                    form.direction === d.value && "border-primary bg-accent text-accent-foreground",
                  )}
                >
                  <d.icon className="size-5" aria-hidden />
                  <span className="font-medium">{d.label}</span>
                  <span className="hidden text-xs text-muted-foreground sm:block">{d.hint}</span>
                </button>
              ))}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="posting_date" label="Date" required error={errors.posting_date}>
                <Input id="posting_date" type="date" value={form.posting_date} onChange={(e) => set("posting_date", e.target.value)} />
              </FormField>
              <CategorySelect
                group="payment_purpose"
                label="Purpose"
                required
                value={form.purpose}
                onChange={(v) => set("purpose", v)}
                filter={(c) => !c.config?.direction || c.config.direction === form.direction}
                error={errors.purpose_category_id ?? errors.purpose_other_text}
              />
            </div>

            {!isTransfer && (
              <FormField
                id="party"
                label={form.direction === "receive" ? "Received from" : "Paid to"}
                error={errors.party_id}
                hint={purpose?.system_key === "employee_salary" ? "Salary payments go to an employee." : undefined}
              >
                {purpose?.system_key === "employee_salary" ? (
                  <EmployeePartyPicker value={form.party_id} onChange={(v) => set("party_id", v)} />
                ) : (
                  <PartyPicker
                    id="party"
                    value={form.party_id}
                    onChange={(v) => set("party_id", v)}
                    kinds={form.direction === "receive" ? ["customer", "other"] : ["supplier", "other"]}
                    invalid={!!errors.party_id}
                  />
                )}
              </FormField>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              {form.direction !== "receive" && (
                <FormField id="paid_from" label={isTransfer ? "From account" : "Paid from"} required error={errors.paid_from_payment_account_id}>
                  <PaymentAccountPicker
                    id="paid_from"
                    value={form.paid_from_payment_account_id}
                    onChange={(v) => set("paid_from_payment_account_id", v)}
                    invalid={!!errors.paid_from_payment_account_id}
                  />
                </FormField>
              )}
              {form.direction !== "pay" && (
                <FormField id="paid_to" label={isTransfer ? "To account" : "Received into"} required error={errors.paid_to_payment_account_id}>
                  <PaymentAccountPicker
                    id="paid_to"
                    value={form.paid_to_payment_account_id}
                    onChange={(v) => set("paid_to_payment_account_id", v)}
                    invalid={!!errors.paid_to_payment_account_id}
                  />
                </FormField>
              )}
              <CategorySelect
                group="payment_method"
                label="Method"
                required
                value={form.method}
                onChange={(v) => set("method", v)}
                error={errors.method_category_id ?? errors.method_other_text}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <FormField id="amount" label={`Amount${isTransfer ? " sent" : ""} (${currency})`} required error={amountError ?? errors.amount}>
                <Input
                  id="amount"
                  inputMode="decimal"
                  className="tabular text-right"
                  value={form.amount}
                  aria-invalid={!!(amountError ?? errors.amount)}
                  onChange={(e) => set("amount", e.target.value.trim())}
                />
              </FormField>
              {currency !== base && (
                <FormField
                  id="exchange_rate"
                  label={`Rate 1 ${currency} = ? ${base}`}
                  error={errors.exchange_rate}
                  hint={rateLookup.isError ? "No stored rate for this date: enter one" : rateTouched ? "Entered manually" : "From stored rates"}
                >
                  <Input
                    id="exchange_rate"
                    inputMode="decimal"
                    className="tabular text-right"
                    value={form.exchange_rate}
                    onChange={(e) => {
                      setRateTouched(true);
                      set("exchange_rate", e.target.value.trim());
                    }}
                  />
                </FormField>
              )}
              <FormField
                id="fee_amount"
                label={`Fee (${currency})`}
                error={errors.fee_amount}
                hint={form.fee_amount ? (form.fee_paid_by === "company" ? "Recorded as our expense" : "Paid by the other side; not posted") : "Processor or bank fee, if any"}
              >
                <div className="flex gap-2">
                  <Input
                    id="fee_amount"
                    inputMode="decimal"
                    className="tabular text-right"
                    value={form.fee_amount}
                    onChange={(e) => set("fee_amount", e.target.value.trim())}
                  />
                  <Select
                    aria-label="Fee paid by"
                    className="w-28"
                    value={form.fee_paid_by}
                    onChange={(e) => set("fee_paid_by", e.target.value as "client" | "company")}
                  >
                    <option value="company">We pay</option>
                    <option value="client">{form.direction === "receive" ? "Client pays" : "They pay"}</option>
                  </Select>
                </div>
              </FormField>
            </div>

            {isTransfer && dst && (
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField
                  id="received_amount"
                  label={`Amount received (${dst.currency})`}
                  error={errors.received_amount}
                  hint={crossCurrency ? "What actually arrived" : "Leave empty if it equals the amount sent"}
                >
                  <Input
                    id="received_amount"
                    inputMode="decimal"
                    className="tabular text-right"
                    value={form.received_amount}
                    onChange={(e) => set("received_amount", e.target.value.trim())}
                  />
                </FormField>
                {crossCurrency && dst.currency !== base && (
                  <FormField id="received_exchange_rate" label={`Rate 1 ${dst.currency} = ? ${base}`} error={errors.received_exchange_rate}>
                    <Input
                      id="received_exchange_rate"
                      inputMode="decimal"
                      className="tabular text-right"
                      value={form.received_exchange_rate}
                      onChange={(e) => set("received_exchange_rate", e.target.value.trim())}
                    />
                  </FormField>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {!isTransfer && (
          <Card>
            <CardHeader>
              <CardTitle>Classification</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <CategorySelect
                group={form.direction === "receive" ? "income_category" : "expense_category"}
                label={form.direction === "receive" ? "Income category" : "Expense category"}
                value={form.category}
                onChange={(v) => set("category", v)}
                error={errors.category_id ?? errors.category_other_text}
              />
              <FormField
                id="counter_account"
                label={form.direction === "receive" ? "Income account" : "Expense account"}
                error={errors.counter_account_id}
                hint="Optional: defaults from the category, project type or purpose."
              >
                <AccountPicker
                  id="counter_account"
                  value={form.counter_account_id}
                  onChange={(v) => set("counter_account_id", v)}
                  roots={form.direction === "receive" ? ["income", "equity", "liability"] : ["expense", "asset", "equity", "liability"]}
                  excludeMoney
                  placeholder="Use default"
                  invalid={!!errors.counter_account_id}
                />
              </FormField>
              <FormField id="project" label="Project" error={errors.project_id}>
                <ProjectPicker id="project" value={form.project_id} onChange={(v) => set("project_id", v)} />
              </FormField>
              {form.direction === "pay" && purpose?.system_key !== "employee_salary" && (
                <FormField id="employee" label="Employee (optional tag)">
                  <EmployeePicker id="employee" value={form.employee_id} onChange={(v) => set("employee_id", v)} />
                </FormField>
              )}
            </CardContent>
          </Card>
        )}

        {requiresSplit && (
          <AllocationEditor
            mode={mode}
            onModeChange={(m) => {
              setSplitTouched(true);
              setMode(m);
            }}
            rows={splits}
            onChange={(rows) => {
              setSplitTouched(true);
              setSplits(rows);
            }}
            computed={preview.data?.allocations}
            eligible={preview.data?.eligible_amount_base}
            baseCurrency={base}
            onUseProjectDefault={form.project_id ? () => void loadProjectDefault(form.project_id) : undefined}
            error={errors.allocations}
          />
        )}

        <Card>
          <CardHeader>
            <CardTitle>Reference</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <FormField id="reference_no" label="Reference number" error={errors.reference_no} hint="Bank reference, transaction hash…">
              <Input id="reference_no" value={form.reference_no} onChange={(e) => set("reference_no", e.target.value)} />
            </FormField>
            <FormField id="description" label="Description" className="sm:col-span-2">
              <Textarea id="description" value={form.description} onChange={(e) => set("description", e.target.value)} />
            </FormField>
          </CardContent>
        </Card>

        <div className="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center justify-end gap-2 border-t bg-background/95 px-4 py-3 backdrop-blur lg:-mx-8 lg:px-8">
          {entry && (
            <Button type="button" variant="ghost" className="mr-auto text-destructive" onClick={() => setConfirmDelete(true)}>
              <Trash2 /> Delete draft
            </Button>
          )}
          {Object.keys(serverErrors).length > 0 && (
            <span className="text-sm text-destructive">Fix: {Object.keys(serverErrors).map(fieldLabel).join(", ")}</span>
          )}
          <Button type="submit" variant="outline" loading={save.isPending && !confirmSubmit} disabled={!form.amount || !!amountError}>
            <Save /> Save draft
          </Button>
          {canSubmit && (
            <Button type="button" disabled={!ready} onClick={() => setConfirmSubmit(true)}>
              <Send /> Submit
            </Button>
          )}
        </div>
      </form>

      <div className="flex flex-col gap-6 xl:sticky xl:top-20 xl:self-start">
        <PostingPreview preview={previewable ? preview.data : undefined} loading={preview.isFetching} />
      </div>

      <ConfirmDialog
        open={confirmSubmit}
        onOpenChange={setConfirmSubmit}
        title="Submit this payment?"
        confirmLabel="Submit and post"
        description={
          <div className="flex flex-col gap-2">
            <p>
              {form.direction === "receive" ? "Receive" : form.direction === "pay" ? "Pay" : "Transfer"}{" "}
              <strong className="tabular">
                {formatAmount(form.amount, precision)} {currency}
              </strong>{" "}
              on {form.posting_date}. This posts to the ledger immediately.
            </p>
            <p>Submitted payments can&apos;t be edited; to correct one you cancel it and enter it again.</p>
          </div>
        }
        onConfirm={onSubmit}
      />
      {entry && (
        <ConfirmDialog
          open={confirmDelete}
          onOpenChange={setConfirmDelete}
          title={`Delete draft ${entry.number}?`}
          description="Drafts have no accounting effect, so deleting one is safe."
          confirmLabel="Delete"
          destructive
          onConfirm={async () => {
            try {
              await api.delete(`/payment-entries/${entry.id}`);
              qc.invalidateQueries({ queryKey: ["payment-entries"] });
              toast.success("Draft deleted");
              router.replace("/accounting/payment-entries");
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not delete");
              throw err;
            }
          }}
        />
      )}
    </div>
  );
}

/** Employee picker that returns the employee's financial party id (what salary payments reference). */
function EmployeePartyPicker({ value, onChange }: { value: string | null; onChange: (partyId: string | null) => void }) {
  const employees = useEmployees();
  const selected = employees.data?.find((e) => e.party_id === value);
  return (
    <EmployeePicker
      id="party"
      value={selected?.id ?? null}
      onChange={(employeeId) => onChange(employees.data?.find((e) => e.id === employeeId)?.party_id ?? null)}
    />
  );
}
