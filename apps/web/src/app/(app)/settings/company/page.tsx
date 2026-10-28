"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { formatPeriodRange, upcomingPeriods } from "@/lib/salary-cycle";
import { useCan } from "@/lib/session";
import type { Company, Currency } from "@/lib/types";

const MONTHS = Array.from({ length: 12 }, (_, i) =>
  new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(2026, i, 1))),
);

type Form = {
  name: string;
  legal_name: string;
  email: string;
  phone: string;
  website: string;
  base_currency: string;
  timezone: string;
  fiscal_year_start_month: number;
  salary_cycle_start_day: number;
  eligible_revenue_basis: string;
};

function toForm(c: Company): Form {
  return {
    name: c.name,
    legal_name: c.legal_name ?? "",
    email: c.email ?? "",
    phone: c.phone ?? "",
    website: c.website ?? "",
    base_currency: c.base_currency,
    timezone: c.timezone,
    fiscal_year_start_month: c.fiscal_year_start_month,
    salary_cycle_start_day: c.salary_cycle_start_day,
    eligible_revenue_basis: String(c.policies.eligible_revenue_basis ?? "net_of_company_fees"),
  };
}

export default function CompanySettingsPage() {
  const can = useCan();
  const editable = can("settings.manage");
  const qc = useQueryClient();
  const company = useQuery({ queryKey: ["company"], queryFn: () => api.get<Company>("/settings/company") });
  const currencies = useQuery({ queryKey: ["currencies"], queryFn: () => api.get<Currency[]>("/currencies") });
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const timezones = useMemo(() => (typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : []), []);

  useEffect(() => {
    if (company.data) setForm(toForm(company.data));
  }, [company.data]);

  const save = useMutation({
    mutationFn: (f: Form) => {
      const { eligible_revenue_basis, ...rest } = f;
      return api.patch<Company>("/settings/company", {
        ...rest,
        version: company.data!.version,
        legal_name: rest.legal_name || null,
        email: rest.email || null,
        phone: rest.phone || null,
        website: rest.website || null,
        policies: { eligible_revenue_basis },
      });
    },
    onSuccess: (updated) => {
      qc.setQueryData(["company"], updated);
      setErrors({});
      toast.success("Company settings saved");
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors());
        toast.error(err.status === 412 ? "Someone else changed these settings. Reload to see the latest." : err.message);
      }
    },
  });

  if (company.isError) return <ErrorState error={company.error} onRetry={() => company.refetch()} />;
  if (!form || !company.data) return <Skeleton className="h-96 w-full" />;

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm({ ...form, [key]: value });
  const preview = upcomingPeriods(new Date(), form.salary_cycle_start_day, 3);
  const fiat = (currencies.data ?? []).filter((c) => !c.is_crypto);

  return (
    <>
      <PageHeader
        title="Company settings"
        description={editable ? "Applies to the whole company." : "Only administrators can change these settings."}
      />
      <form
        className="flex flex-col gap-6"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(form);
        }}
      >
        <fieldset disabled={!editable} className="contents">
          <Card>
            <CardHeader>
              <CardTitle>Company</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <FormField id="name" label="Display name" required error={errors.name}>
                <Input id="name" value={form.name} onChange={(e) => set("name", e.target.value)} required />
              </FormField>
              <FormField id="legal_name" label="Legal name" error={errors.legal_name}>
                <Input id="legal_name" value={form.legal_name} onChange={(e) => set("legal_name", e.target.value)} />
              </FormField>
              <FormField id="email" label="Email" error={errors.email}>
                <Input id="email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
              </FormField>
              <FormField id="phone" label="Phone" error={errors.phone}>
                <Input id="phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
              </FormField>
              <FormField id="website" label="Website" error={errors.website} className="sm:col-span-2">
                <Input id="website" value={form.website} onChange={(e) => set("website", e.target.value)} />
              </FormField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Accounting</CardTitle>
              <CardDescription>The base currency is locked once the first transaction is posted.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <FormField id="base_currency" label="Base currency" error={errors.base_currency}
                hint={company.data.base_currency_locked ? "Locked: transactions exist." : undefined}>
                <Select
                  id="base_currency"
                  value={form.base_currency}
                  disabled={company.data.base_currency_locked}
                  onChange={(e) => set("base_currency", e.target.value)}
                >
                  {fiat.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.code} · {c.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="timezone" label="Time zone" error={errors.timezone} hint="Used for business dates and periods.">
                <Input id="timezone" list="tz-list" value={form.timezone} onChange={(e) => set("timezone", e.target.value)} />
                <datalist id="tz-list">
                  {timezones.map((tz) => (
                    <option key={tz} value={tz} />
                  ))}
                </datalist>
              </FormField>
              <FormField id="fiscal_year_start_month" label="Fiscal year starts in" error={errors.fiscal_year_start_month}>
                <Select
                  id="fiscal_year_start_month"
                  value={form.fiscal_year_start_month}
                  onChange={(e) => set("fiscal_year_start_month", Number(e.target.value))}
                >
                  {MONTHS.map((m, i) => (
                    <option key={m} value={i + 1}>
                      {m}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField
                id="eligible_revenue_basis"
                label="Employee revenue counts"
                error={errors["policies.eligible_revenue_basis"]}
                hint="Whether processor fees paid by the company reduce attributed revenue."
              >
                <Select
                  id="eligible_revenue_basis"
                  value={form.eligible_revenue_basis}
                  onChange={(e) => set("eligible_revenue_basis", e.target.value)}
                >
                  <option value="net_of_company_fees">After fees paid by us (net)</option>
                  <option value="gross">Before fees (gross)</option>
                </Select>
              </FormField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Salary cycle</CardTitle>
              <CardDescription>
                Employee revenue and salary are counted per salary period. Choose the day each period starts.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <FormField
                id="salary_cycle_start_day"
                label="Period starts on day"
                error={errors.salary_cycle_start_day}
                hint="1 = calendar month. 25 = the 25th through the 24th of the next month."
              >
                <Select
                  id="salary_cycle_start_day"
                  value={form.salary_cycle_start_day}
                  onChange={(e) => set("salary_cycle_start_day", Number(e.target.value))}
                >
                  {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                    <option key={d} value={d}>
                      {d === 1 ? "1 (calendar month)" : d}
                    </option>
                  ))}
                </Select>
              </FormField>
              <div className="rounded-md border bg-muted/40 p-3" aria-live="polite">
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Upcoming periods</p>
                <ul className="flex flex-col gap-1 text-sm">
                  {preview.map((p) => (
                    <li key={p.label} className="flex justify-between gap-4">
                      <span className="font-medium">{p.label}</span>
                      <span className="tabular text-muted-foreground">{formatPeriodRange(p)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </CardContent>
          </Card>
        </fieldset>

        {editable && (
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setForm(toForm(company.data!))} disabled={save.isPending}>
              Reset
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save changes
            </Button>
          </div>
        )}
      </form>
    </>
  );
}
