"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Download, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { StatusBadge } from "@/components/payments/entry-view";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { currencyPrecision, useCurrencies } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { Page, PaymentEntry } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const PAGE_SIZE = 25;
const ICON = { receive: ArrowDownLeft, pay: ArrowUpRight, internal_transfer: ArrowLeftRight } as const;

export default function PaymentEntriesPage() {
  const router = useRouter();
  const can = useCan();
  const currencies = useCurrencies();
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ q: "", status: "", direction: "", from: "", to: "" });
  const setFilter = (k: keyof typeof filters, v: string) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };

  const entries = useQuery({
    queryKey: ["payment-entries", page, filters],
    queryFn: () => api.get<Page<PaymentEntry>>("/payment-entries", { page, page_size: PAGE_SIZE, ...filters }),
    placeholderData: keepPreviousData,
  });

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
      {
        accessorKey: "description",
        header: "Description",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="line-clamp-1 max-w-64 text-muted-foreground">{row.original.description ?? row.original.reference_no ?? ""}</span>
        ),
      },
      {
        id: "amount",
        header: () => <span className="block text-right">Amount</span>,
        accessorFn: (e) => Number(e.base_amount ?? e.amount),
        cell: ({ row }) => {
          const e = row.original;
          const out = e.direction === "pay";
          return (
            <span className={`tabular block text-right ${out ? "" : e.direction === "receive" ? "text-success" : ""}`}>
              {out ? "−" : ""}
              {formatAmount(e.amount, currencyPrecision(currencies.data, e.currency))} {e.currency}
            </span>
          );
        },
      },
      { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    ],
    [currencies.data],
  );

  const csvHref = `/api/v1/payment-entries?${new URLSearchParams({ ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), format: "csv" })}`;

  return (
    <>
      <PageHeader
        title="Payment entries"
        description="Every payment received, paid or moved between our accounts. Submitting a payment posts it to the ledger."
        actions={
          <>
            <Button variant="outline" asChild>
              <a href={csvHref}>
                <Download /> CSV
              </a>
            </Button>
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
        <div className="flex flex-col gap-2 border-b p-3 md:flex-row md:flex-wrap">
          <div className="relative md:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search" placeholder="Number, reference, description" className="pl-8" value={filters.q}
              onChange={(e) => setFilter("q", e.target.value)} />
          </div>
          <Select aria-label="Status" className="md:w-36" value={filters.status} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="submitted">Submitted</option>
            <option value="cancelled">Cancelled</option>
          </Select>
          <Select aria-label="Direction" className="md:w-40" value={filters.direction} onChange={(e) => setFilter("direction", e.target.value)}>
            <option value="">All directions</option>
            <option value="receive">Received</option>
            <option value="pay">Paid</option>
            <option value="internal_transfer">Transfers</option>
          </Select>
          <div className="flex items-center gap-2">
            <Input aria-label="From date" type="date" className="md:w-40" value={filters.from} onChange={(e) => setFilter("from", e.target.value)} />
            <span className="text-muted-foreground">–</span>
            <Input aria-label="To date" type="date" className="md:w-40" value={filters.to} onChange={(e) => setFilter("to", e.target.value)} />
          </div>
        </div>
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
