"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Plus, Search, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { ExportMenu } from "@/components/erp/export-menu";
import { MultiSelect } from "@/components/erp/multi-select";
import { EmployeePicker, PartyPicker, PaymentAccountPicker } from "@/components/erp/pickers";
import { StatusBadge } from "@/components/payments/entry-view";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount, formatShort, sign } from "@/lib/money";
import { currencyPrecision, useAccounts, useCompany, useCurrencies, useEmployees, useParty, usePaymentAccounts } from "@/lib/queries";
import { useCan, useMe } from "@/lib/session";
import type { Account, Page, PaymentEntry } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const PAGE_SIZE = 25;
const ICON = { receive: ArrowDownLeft, pay: ArrowUpRight, internal_transfer: ArrowLeftRight } as const;

type Totals = { count: number; received: string; paid: string; transferred: string; base_currency: string };

const MONEY_TYPES: Record<string, string> = { bank: "bank", cash: "cash", crypto_wallet: "wallet", credit_card: "card" };

/** Ledger accounts for the filter, in chart order with groups indented (links from the chart can name any). */
function ledgerOptions(accounts: Account[], selected: string[]) {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const depth = (a: Account): number => (a.parent_id && byId.has(a.parent_id) ? 1 + depth(byId.get(a.parent_id)!) : 0);
  return accounts
    .filter((a) => a.is_active || selected.includes(a.id))
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((a) => ({ value: a.id, label: `${a.code} · ${a.name}`, hint: a.is_group ? "group" : MONEY_TYPES[a.account_type], indent: depth(a) }));
}

const EMPTY = { q: "", status: "submitted", direction: "", from: "", to: "", party_id: "", employee_id: "", payment_account_id: "", account_ids: "", project_id: "" };

function PaymentEntriesList() {
  // ?employee_id=, ?party_id=, ?payment_account_id=, ?account_ids=, ?project_id=, ?direction=, ?from=, ?to= open the list
  // already filtered (links from employee, party and account pages, and from report figures).
  const params = useSearchParams();
  const router = useRouter();
  const can = useCan();
  const currencies = useCurrencies();
  const base = useCompany().data?.base_currency ?? "";
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    ...EMPTY,
    status: params.get("status") ?? EMPTY.status,
    direction: params.get("direction") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    party_id: params.get("party_id") ?? "",
    employee_id: params.get("employee_id") ?? "",
    payment_account_id: params.get("payment_account_id") ?? "",
    account_ids: params.get("account_ids") ?? "",
    project_id: params.get("project_id") ?? "", // from the projects list (no picker of its own)
  });
  // Without payments.create or reports.financial (an employee): only the payments about themselves,
  // read-only, so the filters that need company lookups are hidden.
  const ownOnly = !can("payments.create") && !can("reports.financial");
  // A hired manager only ever sees completed payments to them, so those filters and columns don't apply.
  const isHire = useMe().restricted_access;
  const employees = useEmployees(!ownOnly);
  const accounts = usePaymentAccounts(true, !ownOnly);
  const ledger = useAccounts(!ownOnly);
  const filtered = !!(filters.party_id || filters.employee_id || filters.payment_account_id || filters.account_ids || filters.project_id || filters.q || filters.direction || filters.from || filters.to);
  const setFilter = (k: keyof typeof filters, v: string) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };

  const entries = useQuery({
    queryKey: ["payment-entries", page, filters],
    queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { page, page_size: PAGE_SIZE, ...filters }),
    placeholderData: keepPreviousData,
  });
  const totals = useQuery({
    queryKey: ["payment-entries", "totals", filters],
    queryFn: () => api.get<Totals>("/payment-entries/totals", filters),
    placeholderData: keepPreviousData,
  });
  const who = employees.data?.find((e) => e.id === filters.employee_id)?.full_name;
  const where = accounts.data?.find((a) => a.id === filters.payment_account_id)?.name;
  const ledgerIds = filters.account_ids ? filters.account_ids.split(",") : [];
  const ledgerOpts = useMemo(() => ledgerOptions(ledger.data ?? [], ledgerIds), [ledger.data, filters.account_ids]); // eslint-disable-line react-hooks/exhaustive-deps
  const booked = ledgerIds.length === 1 ? ledger.data?.find((a) => a.id === ledgerIds[0]) : undefined;
  // An employee can narrow their payments to one of their hires. Everything else about them comes from their own list.
  const myHires = useQuery({
    queryKey: ["payment-entries", "my-hires"],
    queryFn: () => api.get<{ party_id: string; full_name: string }[]>("/payment-entries/my-hires"),
    enabled: ownOnly && !isHire,
  });
  const companyParty = useParty(ownOnly ? null : filters.party_id || null).data?.name;
  const party = ownOnly ? myHires.data?.find((h) => h.party_id === filters.party_id)?.full_name : companyParty;

  const columns = useMemo<ColumnDef<PaymentEntry, unknown>[]>(
    () => [
      {
        accessorKey: "posting_date",
        header: "Date",
        cell: ({ row }) => <span className="whitespace-nowrap">{formatDate(row.original.posting_date)}</span>,
      },
      {
        accessorKey: "number",
        header: "Number",
        cell: ({ row }) => {
          const Icon = ICON[row.original.direction as keyof typeof ICON];
          return (
            <Link href={`/accounting/payment-entries/${row.original.id}`} className="flex items-center gap-2 font-mono text-xs hover:underline">
              <Icon className="size-4 text-muted-foreground" aria-label={row.original.direction} />
              {row.original.number}
            </Link>
          );
        },
      },
      {
        id: "party",
        header: "Party / project",
        accessorFn: (e) => e.party_name ?? "",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate">{row.original.party_name ?? (row.original.direction === "internal_transfer" ? "Internal transfer" : "—")}</div>
            {row.original.project_name && <div className="truncate text-xs text-muted-foreground">{row.original.project_name}</div>}
          </div>
        ),
      },
      ...(isHire ? [] : [{
        id: "employees",
        header: "Employees",
        enableSorting: false,
        cell: ({ row }) => {
          const e = row.original;
          // Customer payments: the revenue split. Salary payments and tagged expenses: the employee.
          if (e.allocations.length) {
            return (
              <div className="flex max-w-56 flex-col text-sm">
                {e.allocations.map((a) => (
                  <span key={a.employee_id} className="truncate">
                    {a.employee_name}{" "}
                    <span className="text-xs text-muted-foreground">
                      {a.percent ? `${a.percent.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "")}%` : formatAmount(a.amount)}
                    </span>
                  </span>
                ))}
              </div>
            );
          }
          return <span className="text-sm text-muted-foreground">{e.employee_name ?? "—"}</span>;
        },
      } satisfies ColumnDef<PaymentEntry, unknown>]),
      {
        accessorKey: "description",
        header: isHire ? "Reference" : "Description",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="line-clamp-1 max-w-64 text-muted-foreground">{row.original.description ?? row.original.reference_no ?? ""}</span>
        ),
      },
      {
        id: "amount",
        header: () => <span className="block text-right">Amount</span>,
        accessorFn: (e) => Number(e.my_share ?? e.base_amount ?? e.amount),
        cell: ({ row }) => {
          const e = row.original;
          const out = e.direction === "pay" && !isHire;
          if (e.my_share != null) {
            // Employee view of a shared payment: their share (base currency), with the whole amount below.
            return (
              <span className={`tabular block text-right ${out ? "" : "text-success"}`}>
                {out ? "−" : ""}
                {formatShort(e.my_share)} {base}
                <span className="block text-xs text-muted-foreground">
                  your share of {formatShort(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}
                </span>
              </span>
            );
          }
          return (
            <span className={`tabular block text-right ${out ? "" : e.direction === "receive" ? "text-success" : ""}`}>
              {out ? "−" : ""}
              {formatShort(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}
            </span>
          );
        },
      },
      { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    ],
    [currencies.data, base, isHire],
  );


  return (
    <>
      <PageHeader
        title={isHire ? "Payments" : "Payment entries"}
        description={
          isHire
            ? "What you've been paid, by project."
            : ownOnly
            ? "Payments about you: revenue credited to you, salary paid to you, and expenses tagged to or shared with you."
            : "Every payment received, paid or moved between our accounts. Submitting a payment posts it to the ledger."
        }
        actions={
          <>
            <ExportMenu path="/payment-entries" params={filters} />
            {can("payments.create") && (
              <Button asChild>
                <Link href="/accounting/payment-entries/new">
                  <Plus /> New payment
                </Link>
              </Button>
            )}
          </>
        }
      />
      <Card>
        {/* Row 1: what and when. Row 2: who and where. */}
        <div className="flex flex-col gap-2 border-b p-3">
          <div className="flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center">
            <div className="relative md:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
              <Input aria-label="Search" placeholder={isHire ? "Number or reference" : "Number, reference, description"} className="pl-8" value={filters.q}
                onChange={(e) => setFilter("q", e.target.value)} />
            </div>
            {!isHire && (
              <>
                <Select aria-label="Status" className="md:w-36" value={filters.status} onChange={(e) => setFilter("status", e.target.value)}>
                  <option value="">All statuses</option>
                  <option value="submitted">Submitted</option>
                  <option value="draft">Draft</option>
                  <option value="cancelled">Cancelled</option>
                </Select>
                <Select aria-label="Direction" className="md:w-40" value={filters.direction} onChange={(e) => setFilter("direction", e.target.value)}>
                  <option value="">All directions</option>
                  <option value="receive">Received</option>
                  <option value="pay">Paid</option>
                  <option value="internal_transfer">Transfers</option>
                </Select>
              </>
            )}
            <div className="flex items-center gap-2">
              <Input aria-label="From date" type="date" className="md:w-40" value={filters.from} onChange={(e) => setFilter("from", e.target.value)} />
              <span className="text-muted-foreground">–</span>
              <Input aria-label="To date" type="date" className="md:w-40" value={filters.to} onChange={(e) => setFilter("to", e.target.value)} />
            </div>
          </div>
          <div className="flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center">
            {ownOnly && (myHires.data?.length ?? 0) > 0 && (
              <Select aria-label="Hired manager" className="md:w-64" value={filters.party_id} onChange={(e) => setFilter("party_id", e.target.value)}>
                <option value="">Any</option>
                {myHires.data?.map((h) => <option key={h.party_id} value={h.party_id}>{h.full_name}</option>)}
              </Select>
            )}
            {!ownOnly && (
            <>
            <div className="md:w-64">
              <PartyPicker id="f_party" kinds={["customer", "supplier", "other"]} value={filters.party_id || null}
                onChange={(v) => setFilter("party_id", v ?? "")} placeholder="Any customer or supplier" />
            </div>
            <div className="md:w-56">
              <EmployeePicker id="f_employee" value={filters.employee_id || null} onChange={(v) => setFilter("employee_id", v ?? "")} placeholder="Any employee" />
            </div>
            <div className="md:w-56">
              <PaymentAccountPicker id="f_account" value={filters.payment_account_id || null} onChange={(v) => setFilter("payment_account_id", v ?? "")} placeholder="Any bank / cash account" />
            </div>
            <div className="md:w-64" title="Income, expense or other ledger accounts the payment is booked to (fees and FX lines count too). A payment matching any of them is shown; a group includes the accounts under it.">
              <MultiSelect
                options={ledgerOpts}
                value={ledgerIds}
                onChange={(v) => setFilter("account_ids", v.join(","))}
                placeholder="Any ledger account"
                noun="ledger accounts"
              />
            </div>
            </>
            )}
            {filtered && (
              <Button variant="ghost" size="sm" onClick={() => { setFilters(EMPTY); setPage(1); }}><X /> Clear filters</Button>
            )}
          </div>
        </div>
        {totals.data && (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b bg-muted/30 px-4 py-2 text-sm">
            <span className="font-medium">
              {totals.data.count} entr{totals.data.count === 1 ? "y" : "ies"}
              {party && <> with {party}</>}
              {who && <> for {who}</>}
              {where && <> through {where}</>}
              {filters.project_id && <> on the chosen project</>}
              {booked && <> booked to {booked.code} {booked.name}{booked.is_group ? " (and the accounts under it)" : ""}</>}
              {ledgerIds.length > 1 && <> booked to any of {ledgerIds.length} ledger accounts</>}
            </span>
            {!isHire && <span className="text-success">Received <span className="tabular">{formatAmount(totals.data.received)}</span></span>}
            <span>{isHire ? "Paid to you" : "Paid"} <span className="tabular">{formatAmount(totals.data.paid)}</span></span>
            {sign(totals.data.transferred) !== 0 && <span className="text-muted-foreground">Transfers <span className="tabular">{formatAmount(totals.data.transferred)}</span></span>}
            <span className="text-xs text-muted-foreground">
              {totals.data.base_currency}{!isHire && ", submitted only"}
              {isHire ? "" : ownOnly ? " · shared payments count with your share" : who ? " · includes revenue split to them, salary paid to them and expenses tagged to or shared with them" : ""}
            </span>
          </div>
        )}
        <DataTable
          columns={columns}
          data={entries.data?.items}
          isLoading={entries.isLoading}
          error={entries.error}
          onRetry={() => entries.refetch()}
          getRowId={(e) => e.id}
          pagination={entries.data && { page, pageSize: PAGE_SIZE, total: entries.data.total, onPageChange: setPage }}
          empty={
            <EmptyState
              title="No payments yet"
              description="Record a customer payment, an expense, or a transfer between accounts."
              action={can("payments.create") ? <Button onClick={() => router.push("/accounting/payment-entries/new")}><Plus /> New payment</Button> : undefined}
            />
          }
        />
      </Card>
    </>
  );
}

export default function PaymentEntriesPage() {
  return (
    <Suspense>
      <PaymentEntriesList />
    </Suspense>
  );
}
