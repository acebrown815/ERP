"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable } from "@/components/erp/data-table";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Input, Select } from "@/components/ui/input";
import { Badge, Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { Company, Currency, ExchangeRate, Page } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const DECIMAL = /^\d+(\.\d{1,12})?$/;

function CurrencyDialog({ currency, onClose }: { currency?: Currency; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    code: currency?.code ?? "",
    name: currency?.name ?? "",
    symbol: currency?.symbol ?? "",
    precision: currency?.precision ?? 2,
    is_crypto: currency?.is_crypto ?? false,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () =>
      currency
        ? api.patch<Currency>(`/currencies/${currency.code}`, { name: form.name, symbol: form.symbol || null, precision: form.precision })
        : api.post<Currency>("/currencies", { ...form, symbol: form.symbol || null }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["currencies"] });
      toast.success(currency ? `${c.code} updated` : `${c.code} added`);
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        if (!err.errors.length) toast.error(err.message);
      }
    },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{currency ? `Edit ${currency.code}` : "Add currency"}</DialogTitle>
          <DialogDescription>
            {currency ? "The code and type can't change. Decimal places can only go up once the currency has been used." : "Fiat currencies and crypto assets are both supported."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="cur_code" label="Code" required error={errors.code}>
            <Input id="cur_code" value={form.code} maxLength={10} className="uppercase" disabled={!!currency} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </FormField>
          <FormField id="cur_name" label="Name" required error={errors.name}>
            <Input id="cur_name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </FormField>
          <FormField id="cur_symbol" label="Symbol">
            <Input id="cur_symbol" value={form.symbol} maxLength={10} onChange={(e) => setForm({ ...form, symbol: e.target.value })} />
          </FormField>
          <FormField id="cur_precision" label="Decimal places" error={errors.precision} hint="2 for most fiat, up to 18 for crypto.">
            <Input
              id="cur_precision"
              type="number"
              min={0}
              max={18}
              value={form.precision}
              onChange={(e) => setForm({ ...form, precision: Number(e.target.value) })}
            />
          </FormField>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={form.is_crypto} disabled={!!currency} onChange={(e) => setForm({ ...form, is_crypto: e.target.checked })} />
          This is a crypto asset
        </label>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!form.code || !form.name} onClick={() => create.mutate()}>
            {currency ? "Save" : "Add currency"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RateDialog({ currencies, base, rate: editing, onClose }: { currencies: Currency[]; base: string; rate?: ExchangeRate; onClose: () => void }) {
  const qc = useQueryClient();
  const [from, setFrom] = useState(editing?.from_currency ?? currencies.find((c) => c.code !== base)?.code ?? "");
  const [to, setTo] = useState(editing?.to_currency ?? base);
  const [date, setDate] = useState(editing?.rate_date ?? new Date().toISOString().slice(0, 10));
  const [rate, setRate] = useState(editing ? String(editing.rate).replace(/\.?0+$/, "") : "");
  const valid = from && to && from !== to && DECIMAL.test(rate) && Number(rate) > 0;
  const save = useMutation({
    mutationFn: async () => {
      const saved = await api.put<ExchangeRate>("/exchange-rates", { from_currency: from, to_currency: to, rate_date: date, rate });
      // Moved to another pair or date: the old row would otherwise stay as a separate rate.
      if (editing && saved.id !== editing.id) await api.delete(`/exchange-rates/${editing.id}`);
      return saved;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["exchange-rates"] });
      toast.success(`Rate saved: 1 ${from} = ${rate} ${to}`);
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not save rate"),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "Edit exchange rate" : "Exchange rate"}</DialogTitle>
          <DialogDescription>
            Saving a rate for a pair and date that already exists replaces it. Payments already submitted keep the rate they were posted with.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="rate_from" label="From">
            <Select id="rate_from" value={from} onChange={(e) => setFrom(e.target.value)}>
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField id="rate_to" label="To">
            <Select id="rate_to" value={to} onChange={(e) => setTo(e.target.value)}>
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField id="rate_date" label="Date">
            <Input id="rate_date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </FormField>
          <FormField
            id="rate_value"
            label={`1 ${from || "…"} =`}
            hint={to ? `in ${to}` : undefined}
            error={rate && !DECIMAL.test(rate) ? "Up to 12 decimal places" : undefined}
          >
            <Input id="rate_value" inputMode="decimal" className="tabular" value={rate} onChange={(e) => setRate(e.target.value.trim())} />
          </FormField>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>
            Save rate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function CurrenciesPage() {
  const can = useCan();
  const manage = can("currencies.manage");
  const qc = useQueryClient();
  const [addingCurrency, setAddingCurrency] = useState(false);
  const [addingRate, setAddingRate] = useState(false);
  const [editingCurrency, setEditingCurrency] = useState<Currency | null>(null);
  const [editingRate, setEditingRate] = useState<ExchangeRate | null>(null);
  const [ratePage, setRatePage] = useState(1);

  const company = useQuery({ queryKey: ["company"], queryFn: () => api.get<Company>("/settings/company") });
  const currencies = useQuery({
    queryKey: ["currencies", "all"],
    queryFn: () => api.get<Currency[]>("/currencies", { include_inactive: true }),
  });
  const rates = useQuery({
    queryKey: ["exchange-rates", ratePage],
    queryFn: () => api.get<Page<ExchangeRate>>("/exchange-rates", { page: ratePage, page_size: 20 }),
    placeholderData: keepPreviousData,
  });
  const base = company.data?.base_currency ?? "USD";

  const toggle = useMutation({
    mutationFn: (c: Currency) => api.patch<Currency>(`/currencies/${c.code}`, { is_active: !c.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["currencies"] }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update"),
  });
  const removeRate = useMutation({
    mutationFn: (r: ExchangeRate) => api.delete(`/exchange-rates/${r.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["exchange-rates"] });
      toast.success("Rate deleted");
    },
  });

  const currencyColumns = useMemo<ColumnDef<Currency, unknown>[]>(
    () => [
      {
        accessorKey: "code",
        header: "Code",
        cell: ({ row }) => (
          <span className="font-mono font-medium">
            {row.original.code}
            {row.original.code === base && <Badge className="ml-2">Base</Badge>}
          </span>
        ),
      },
      { accessorKey: "name", header: "Name" },
      { accessorKey: "symbol", header: "Symbol", cell: ({ getValue }) => (getValue() as string) || "—" },
      { accessorKey: "precision", header: "Decimals", cell: ({ getValue }) => <span className="tabular">{getValue() as number}</span> },
      { accessorKey: "is_crypto", header: "Type", cell: ({ getValue }) => (getValue() ? <Badge variant="outline">Crypto</Badge> : "Fiat") },
      {
        accessorKey: "is_active",
        header: "Status",
        cell: ({ row }) =>
          manage && row.original.code !== base ? (
            <Button variant="ghost" size="sm" onClick={() => toggle.mutate(row.original)}>
              {row.original.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="muted">Inactive</Badge>}
            </Button>
          ) : row.original.is_active ? (
            <Badge variant="success">Active</Badge>
          ) : (
            <Badge variant="muted">Inactive</Badge>
          ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) =>
          manage && (
            <Button variant="ghost" size="icon" aria-label={`Edit ${row.original.code}`} onClick={() => setEditingCurrency(row.original)}>
              <Pencil />
            </Button>
          ),
      },
    ],
    [base, manage, toggle],
  );

  const rateColumns = useMemo<ColumnDef<ExchangeRate, unknown>[]>(
    () => [
      { accessorKey: "rate_date", header: "Date", cell: ({ getValue }) => formatDate(getValue() as string) },
      {
        id: "pair",
        header: "Pair",
        accessorFn: (r) => `${r.from_currency}/${r.to_currency}`,
        cell: ({ getValue }) => <span className="font-mono">{getValue() as string}</span>,
      },
      {
        accessorKey: "rate",
        header: "Rate",
        cell: ({ row }) => (
          <span className="tabular">
            1 {row.original.from_currency} = {String(row.original.rate).replace(/\.?0+$/, "")} {row.original.to_currency}
          </span>
        ),
      },
      { accessorKey: "source", header: "Source", cell: ({ getValue }) => <Badge variant="muted">{getValue() as string}</Badge> },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) =>
          manage && (
            <div className="flex justify-end">
              <Button variant="ghost" size="icon" aria-label="Edit rate" onClick={() => setEditingRate(row.original)}>
                <Pencil />
              </Button>
              <Button variant="ghost" size="icon" aria-label="Delete rate" onClick={() => removeRate.mutate(row.original)}>
                <Trash2 />
              </Button>
            </div>
          ),
      },
    ],
    [manage, removeRate],
  );

  const active = (currencies.data ?? []).filter((c) => c.is_active);

  return (
    <>
      <PageHeader
        title="Currencies & exchange rates"
        description={`Amounts are converted to the base currency (${base}) at the rate on the transaction date.`}
      />
      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>Currencies</CardTitle>
              <CardDescription>Inactive currencies can&apos;t be used on new transactions.</CardDescription>
            </div>
            {manage && (
              <Button size="sm" onClick={() => setAddingCurrency(true)}>
                <Plus /> Add currency
              </Button>
            )}
          </CardHeader>
          <DataTable
            columns={currencyColumns}
            data={currencies.data}
            isLoading={currencies.isLoading}
            error={currencies.error}
            getRowId={(c) => c.code}
          />
        </Card>
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>Exchange rates</CardTitle>
              <CardDescription>The most recent rate on or before a transaction date is used. Reverse pairs are inverted automatically.</CardDescription>
            </div>
            {manage && (
              <Button size="sm" onClick={() => setAddingRate(true)} disabled={!active.length}>
                <Plus /> Add rate
              </Button>
            )}
          </CardHeader>
          <DataTable
            columns={rateColumns}
            data={rates.data?.items}
            isLoading={rates.isLoading}
            error={rates.error}
            getRowId={(r) => r.id}
            pagination={rates.data && { page: ratePage, pageSize: 20, total: rates.data.total, onPageChange: setRatePage }}
          />
        </Card>
      </div>
      {addingCurrency && <CurrencyDialog onClose={() => setAddingCurrency(false)} />}
      {addingRate && <RateDialog currencies={active} base={base} onClose={() => setAddingRate(false)} />}
      {editingCurrency && <CurrencyDialog currency={editingCurrency} onClose={() => setEditingCurrency(null)} />}
      {editingRate && <RateDialog currencies={active} base={base} rate={editingRate} onClose={() => setEditingRate(null)} />}
    </>
  );
}
