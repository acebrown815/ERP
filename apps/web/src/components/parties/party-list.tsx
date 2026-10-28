"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { KIND_LABEL, PartyDialog, type PartyKind } from "@/components/parties/party-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox, Input } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { Page, Party } from "@/lib/types";

export function PartyList({ kind }: { kind: PartyKind }) {
  const can = useCan();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [creating, setCreating] = useState(false);
  const parties = useQuery({
    queryKey: ["parties", kind, page, q, showInactive],
    queryFn: () => api.get<Page<Party>>("/parties", { kind, page, page_size: 25, q, is_active: showInactive ? undefined : true }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<Party, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: ({ row }) => (
          <Link href={`/parties/${row.original.id}`} className="font-medium hover:underline">
            {row.original.name}
            {!row.original.is_active && <Badge variant="muted" className="ml-2">Inactive</Badge>}
          </Link>
        ),
      },
      { accessorKey: "number", header: "Number", cell: ({ getValue }) => <span className="font-mono text-xs">{getValue() as string}</span> },
      { accessorKey: "contact_name", header: "Contact", cell: ({ row }) => row.original.contact_name ?? "—" },
      { accessorKey: "email", header: "Email", cell: ({ row }) => row.original.email ?? "—" },
      { accessorKey: "default_currency", header: "Currency", cell: ({ row }) => row.original.default_currency ?? "—" },
    ],
    [],
  );
  const label = KIND_LABEL[kind];
  return (
    <>
      <PageHeader
        title={label.many}
        actions={can("parties.manage") && <Button onClick={() => setCreating(true)}><Plus /> New {label.one.toLowerCase()}</Button>}
      />
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b p-3">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search" placeholder="Name, number or email" className="pl-8" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Checkbox checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show inactive
          </label>
        </div>
        <DataTable columns={columns} data={parties.data?.items} isLoading={parties.isLoading} error={parties.error}
          getRowId={(p) => p.id} pagination={parties.data && { page, pageSize: 25, total: parties.data.total, onPageChange: setPage }}
          empty={<EmptyState title={`No ${label.many.toLowerCase()} yet`} description="Add them here, or import a CSV under Settings → Data Import." />} />
      </Card>
      {creating && <PartyDialog kind={kind} party={null} onClose={() => setCreating(false)} />}
    </>
  );
}
