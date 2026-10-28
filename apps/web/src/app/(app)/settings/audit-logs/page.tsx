"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { AuditEntry, Page, User } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const PAGE_SIZE = 50;
const ACTION_FILTERS = [
  { value: "", label: "All actions" },
  { value: "auth.", label: "Sign-ins" },
  { value: "user.", label: "Users" },
  { value: "role.", label: "Roles" },
  { value: "category.", label: "Categories" },
  { value: "company_settings.", label: "Company settings" },
  { value: "currency.", label: "Currencies" },
  { value: "exchange_rate.", label: "Exchange rates" },
  { value: "attachment.", label: "Attachments" },
];

function Changes({ entry }: { entry: AuditEntry }) {
  const keys = [...new Set([...Object.keys(entry.before ?? {}), ...Object.keys(entry.after ?? {})])];
  if (!keys.length) return <span className="text-muted-foreground">—</span>;
  const show = (v: unknown) => (v === null || v === undefined ? "∅" : typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {keys.map((k) => (
        <Fragment key={k}>
          <dt className="font-mono text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words">
            {entry.before && k in entry.before && (
              <>
                <span className="text-destructive line-through">{show(entry.before[k])}</span>
                {entry.after && k in entry.after && " → "}
              </>
            )}
            {entry.after && k in entry.after && <span>{show(entry.after[k])}</span>}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}

export default function AuditLogPage() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [entityId, setEntityId] = useState("");

  const logs = useQuery({
    queryKey: ["audit-logs", page, action, entityId],
    queryFn: () => api.get<Page<AuditEntry>>("/audit-logs", { page, page_size: PAGE_SIZE, action, entity_id: entityId.trim() }),
    placeholderData: keepPreviousData,
  });
  // Resolve actor names when the viewer may list users; otherwise ids are shown.
  const users = useQuery({
    queryKey: ["users", "all-for-audit"],
    queryFn: () => api.get<Page<User>>("/users", { page_size: 200 }),
    retry: false,
  });
  const verify = useQuery({
    queryKey: ["audit-verify"],
    queryFn: () => api.get<{ ok: boolean; first_broken_id: number | null; rows_checked: number }>("/audit-logs/verify"),
    enabled: false,
  });
  const names = useMemo(() => new Map((users.data?.items ?? []).map((u) => [u.id, u.full_name])), [users.data]);

  const columns = useMemo<ColumnDef<AuditEntry, unknown>[]>(
    () => [
      { accessorKey: "at", header: "When", cell: ({ getValue }) => <span className="whitespace-nowrap">{formatDateTime(getValue() as string)}</span> },
      {
        accessorKey: "actor_user_id",
        header: "Who",
        cell: ({ getValue }) => {
          const id = getValue() as string | null;
          return id ? names.get(id) ?? <span className="font-mono text-xs">{id.slice(0, 8)}</span> : <span className="text-muted-foreground">System</span>;
        },
      },
      { accessorKey: "action", header: "Action", cell: ({ getValue }) => <Badge variant="muted" className="font-mono">{getValue() as string}</Badge> },
      {
        id: "entity",
        header: "Record",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="text-xs">
            <div>{row.original.entity_type}</div>
            {row.original.entity_id && (
              <button
                type="button"
                className="font-mono text-muted-foreground hover:text-foreground hover:underline"
                title="Show only this record"
                onClick={() => {
                  setEntityId(row.original.entity_id!);
                  setPage(1);
                }}
              >
                {row.original.entity_id.slice(0, 13)}…
              </button>
            )}
          </div>
        ),
      },
      { id: "changes", header: "Changes", enableSorting: false, cell: ({ row }) => <Changes entry={row.original} /> },
      { accessorKey: "ip", header: "IP", cell: ({ getValue }) => <span className="font-mono text-xs text-muted-foreground">{(getValue() as string) ?? "—"}</span> },
    ],
    [names],
  );

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every sign-in and change to sensitive data. Entries can't be edited or deleted, and each one is chained to the previous so tampering is detectable."
        actions={
          <Button variant="outline" loading={verify.isFetching} onClick={() => verify.refetch()}>
            {verify.data && !verify.data.ok ? <ShieldAlert className="text-destructive" /> : <ShieldCheck />}
            Verify integrity
          </Button>
        }
      />
      {verify.data && (
        <div
          role="status"
          className={
            verify.data.ok
              ? "mb-4 rounded-md border border-success/30 bg-success/10 px-4 py-2 text-sm"
              : "mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive"
          }
        >
          {verify.data.ok
            ? `Chain intact: ${verify.data.rows_checked} entries verified.`
            : `Chain broken at entry #${verify.data.first_broken_id}. Contact your administrator.`}
        </div>
      )}
      <Card>
        <div className="flex flex-col gap-2 border-b p-3 sm:flex-row">
          <Select
            aria-label="Filter by action"
            className="sm:w-56"
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
          >
            {ACTION_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </Select>
          <Input
            aria-label="Filter by record id"
            placeholder="Record id"
            className="sm:w-80"
            value={entityId}
            onChange={(e) => {
              setEntityId(e.target.value);
              setPage(1);
            }}
          />
          {(action || entityId) && (
            <Button
              variant="ghost"
              onClick={() => {
                setAction("");
                setEntityId("");
                setPage(1);
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
        <DataTable
          columns={columns}
          data={logs.data?.items}
          isLoading={logs.isLoading}
          error={logs.error}
          onRetry={() => logs.refetch()}
          getRowId={(e) => String(e.id)}
          pagination={logs.data && { page, pageSize: PAGE_SIZE, total: logs.data.total, onPageChange: setPage }}
        />
      </Card>
    </>
  );
}
