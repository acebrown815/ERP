"use client";

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { pageItems, parsePageInput } from "@/lib/pagination";

export type Pagination = { page: number; pageSize: number; total: number; onPageChange: (page: number) => void };

/** With this few pages, every page has its own button or is one click away, so no "Go to page" box. */
const PAGE_BOX_FROM = 7;

/**
 * Shared table: client-side sorting for the loaded rows (or server-side with `sort`, which sorts
 * across pages), optional server-side pagination, and consistent loading / error / empty states.
 */
export function DataTable<T>({
  columns,
  data,
  isLoading,
  error,
  onRetry,
  pagination,
  sort,
  empty,
  getRowId,
}: {
  columns: ColumnDef<T, unknown>[];
  data: T[] | undefined;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  pagination?: Pagination;
  /** The server sorts: rows are shown in the order given, and clicking a header calls onChange. */
  sort?: { value: SortingState; onChange: (sorting: SortingState) => void };
  empty?: ReactNode;
  getRowId?: (row: T) => string;
}) {
  const [localSorting, setLocalSorting] = useState<SortingState>([]);
  const sorting = sort?.value ?? localSorting;
  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    manualSorting: !!sort,
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sorting) : updater;
      if (sort) sort.onChange(next);
      else setLocalSorting(next);
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  });

  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (isLoading) return <TableSkeleton />;

  const rows = table.getRowModel().rows;
  const lastPage = pagination ? Math.max(1, Math.ceil(pagination.total / pagination.pageSize)) : 1;

  return (
    <div>
      <Table>
        <THead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((header) => {
                const sortable = header.column.getCanSort();
                const dir = header.column.getIsSorted();
                return (
                  <TH
                    key={header.id}
                    style={{ width: header.column.columnDef.size }}
                    aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}
                  >
                    {header.isPlaceholder ? null : sortable ? (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 uppercase hover:text-foreground"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {dir === "asc" ? <ArrowUp className="size-3" /> : dir === "desc" ? <ArrowDown className="size-3" /> : null}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TH>
                );
              })}
            </tr>
          ))}
        </THead>
        <TBody>
          {rows.map((row) => (
            <TR key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TD key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TD>
              ))}
            </TR>
          ))}
        </TBody>
      </Table>
      {rows.length === 0 && (empty ?? <EmptyState title="Nothing here yet" />)}
      {pagination && pagination.total > pagination.pageSize && (
        <PageControls pagination={pagination} lastPage={lastPage} />
      )}
    </div>
  );
}

function PageControls({ pagination, lastPage }: { pagination: Pagination; lastPage: number }) {
  const { page, pageSize, total, onPageChange } = pagination;
  const [typed, setTyped] = useState("");
  const typedPage = parsePageInput(typed, lastPage);

  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t px-3 py-2 text-sm text-muted-foreground">
      <span className="tabular">
        {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total} · Page {page} of {lastPage}
      </span>
      <div className="flex flex-wrap items-center gap-1">
        <Button variant="outline" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          <ChevronLeft />
        </Button>
        {pageItems(page, lastPage).map((item, i) =>
          item === "gap" ? (
            <span key={`gap-${i}`} className="px-1" aria-hidden>…</span>
          ) : (
            <Button
              key={item}
              variant={item === page ? "secondary" : "ghost"}
              size="sm"
              className="tabular min-w-9 px-2"
              aria-label={`Page ${item}`}
              aria-current={item === page ? "page" : undefined}
              onClick={() => item !== page && onPageChange(item)}
            >
              {item}
            </Button>
          ),
        )}
        <Button variant="outline" size="icon" aria-label="Next page" disabled={page >= lastPage} onClick={() => onPageChange(page + 1)}>
          <ChevronRight />
        </Button>
        {lastPage > PAGE_BOX_FROM && (
          <form
            className="ml-2 flex items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (typedPage === null) return;
              onPageChange(typedPage);
              setTyped("");
            }}
          >
            <label htmlFor="go_to_page" className="whitespace-nowrap">Go to page</label>
            <Input id="go_to_page" inputMode="numeric" className="h-8 w-16 tabular" value={typed} onChange={(e) => setTyped(e.target.value)} />
            <Button type="submit" variant="outline" size="sm" disabled={typedPage === null}>Go</Button>
          </form>
        )}
      </div>
    </nav>
  );
}
