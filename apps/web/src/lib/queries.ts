"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  Account,
  Company,
  Currency,
  Department,
  Employee,
  HireOption,
  Formula,
  Page,
  Party,
  PaymentAccount,
  Project,
  SalaryPeriod,
} from "@/lib/types";

// Shared lookups. Lists that stay small (accounts, payment accounts, employees, projects) load once.

export function useCompany() {
  return useQuery({ queryKey: ["company"], queryFn: () => api.get<Company>("/settings/company"), staleTime: 60_000 });
}

export function useCurrencies() {
  return useQuery({ queryKey: ["currencies"], queryFn: () => api.get<Currency[]>("/currencies"), staleTime: 300_000 });
}

export function useAccounts(enabled = true) {
  return useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts"), enabled });
}

export function usePaymentAccounts(includeInactive = false, enabled = true) {
  return useQuery({
    queryKey: ["payment-accounts", includeInactive],
    queryFn: () => api.get<PaymentAccount[]>("/payment-accounts", { include_inactive: includeInactive }),
    enabled,
  });
}

export function useEmployees(enabled = true) {
  return useQuery({
    queryKey: ["employees", "all"],
    queryFn: async () => (await api.get<Page<Employee>>("/employees", { page_size: 200 })).items,
    enabled,
  });
}

export function useDepartments() {
  return useQuery({ queryKey: ["departments"], queryFn: () => api.get<Department[]>("/departments") });
}

/** Active hires to pick from on a project (names only). */
export function useHireOptions(enabled = true) {
  return useQuery({ queryKey: ["hire-options"], queryFn: () => api.get<HireOption[]>("/hires/options"), enabled });
}

export function useProjects(enabled = true) {
  return useQuery({
    queryKey: ["projects", "all"],
    queryFn: async () => (await api.get<Page<Project>>("/projects", { page_size: 200 })).items,
    enabled,
  });
}

export function useParty(id: string | null | undefined) {
  return useQuery({ queryKey: ["party", id], queryFn: () => api.get<Party>(`/parties/${id}`), enabled: !!id });
}

export function currencyPrecision(currencies: Currency[] | undefined, code: string | null | undefined): number {
  return currencies?.find((c) => c.code === code)?.precision ?? 2;
}

export function useSalaryPeriods(enabled = true) {
  return useQuery({ queryKey: ["salary-periods"], queryFn: () => api.get<SalaryPeriod[]>("/salary-periods"), enabled });
}

export function useFormulas(enabled = true) {
  return useQuery({ queryKey: ["comp-formulas"], queryFn: () => api.get<Formula[]>("/comp-formulas"), enabled });
}
