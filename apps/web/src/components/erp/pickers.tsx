"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Combobox } from "@/components/erp/combobox";
import { api } from "@/lib/api";
import { useAccounts, useCompany, useEmployees, useHireOptions, useParty, usePaymentAccounts, useProjects } from "@/lib/queries";
import type { Account, Page, Party } from "@/lib/types";

type Common = {
  id?: string;
  value: string | null;
  onChange: (v: string | null) => void;
  invalid?: boolean;
  disabled?: boolean;
  clearable?: boolean;
};

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  bank: "Bank",
  cash: "Cash",
  crypto_wallet: "Crypto wallet",
  credit_card: "Credit card",
};

export function AccountPicker({
  roots,
  leafOnly = true,
  groupsOnly = false,
  excludeMoney = false,
  placeholder = "Choose account…",
  ...rest
}: Common & { roots?: string[]; leafOnly?: boolean; groupsOnly?: boolean; excludeMoney?: boolean; placeholder?: string }) {
  const { data = [] } = useAccounts();
  const base = useCompany().data?.base_currency;
  const options = data
    .filter((a: Account) => a.is_active)
    .filter((a) => !roots || roots.includes(a.root_type))
    .filter((a) => (groupsOnly ? a.is_group : leafOnly ? !a.is_group : true))
    .filter((a) => !excludeMoney || !ACCOUNT_TYPE_LABEL[a.account_type])
    .map((a) => ({ value: a.id, label: `${a.code} · ${a.name}`, hint: a.currency !== base ? a.currency : undefined }));
  return <Combobox {...rest} options={options} placeholder={placeholder} />;
}

export function PaymentAccountPicker({ placeholder = "Choose account…", ...rest }: Common & { placeholder?: string }) {
  const { data = [] } = usePaymentAccounts();
  const options = data.map((p) => ({
    value: p.id,
    label: p.name,
    hint: `${ACCOUNT_TYPE_LABEL[p.kind] ?? p.kind} · ${p.currency}`,
  }));
  return <Combobox {...rest} options={options} placeholder={placeholder} />;
}

export function PartyPicker({
  kinds,
  placeholder = "Choose…",
  ...rest
}: Common & { kinds?: ("customer" | "supplier" | "other")[]; placeholder?: string }) {
  const [q, setQ] = useState("");
  const search = useQuery({
    queryKey: ["party-search", kinds?.join(","), q],
    queryFn: async () => {
      const kindsToQuery = kinds?.length === 1 ? kinds : [undefined];
      const pages = await Promise.all(
        kindsToQuery.map((kind) => api.get<Page<Party>>("/parties", { q, kind, page_size: 50, is_active: true })),
      );
      return pages.flatMap((p) => p.items).filter((p) => !kinds || kinds.includes(p.kind as "customer"));
    },
  });
  const selected = useParty(rest.value);
  const options = (search.data ?? []).map((p) => ({ value: p.id, label: p.name, hint: `${p.number} · ${p.kind}` }));
  return (
    <Combobox {...rest} options={options} onSearch={setQ} selectedLabel={selected.data?.name} placeholder={placeholder} />
  );
}

export function EmployeePicker({
  placeholder = "Choose employee…",
  excludeHires = false,
  ...rest
}: Common & {
  placeholder?: string;
  /** Leave out hired managers: for anything about revenue, salary or the project team, which they aren't part of. */
  excludeHires?: boolean;
}) {
  const { data = [] } = useEmployees();
  const options = data
    .filter((e) => e.status !== "terminated" || e.id === rest.value)
    .filter((e) => !excludeHires || !e.is_hired_manager || e.id === rest.value)
    .map((e) => ({ value: e.id, label: e.full_name, hint: [e.number, e.job_title].filter(Boolean).join(" · ") }));
  return <Combobox {...rest} options={options} placeholder={placeholder} />;
}

/** Active hired managers. `currentName` keeps a project's current hire showing even if they've since left. */
export function HirePicker({ placeholder = "No hire", currentName, ...rest }: Common & { placeholder?: string; currentName?: string | null }) {
  const { data = [] } = useHireOptions();
  const options = data.map((h) => ({ value: h.id, label: h.full_name }));
  if (rest.value && currentName && !options.some((o) => o.value === rest.value)) options.unshift({ value: rest.value, label: currentName });
  return <Combobox {...rest} options={options} placeholder={placeholder} />;
}

export function ProjectPicker({
  placeholder = "Choose project…",
  onlyWithHire = false,
  ...rest
}: Common & { placeholder?: string; onlyWithHire?: boolean }) {
  const { data = [] } = useProjects();
  const options = data
    .filter((p) => !onlyWithHire || p.hire_employee_id || p.id === rest.value)
    .map((p) => ({
      value: p.id,
      label: p.name,
      hint: onlyWithHire && p.hire_name ? `Hire: ${p.hire_name}` : `${p.number} · ${p.status.replace("_", " ")}`,
    }));
  return <Combobox {...rest} options={options} placeholder={placeholder} />;
}
