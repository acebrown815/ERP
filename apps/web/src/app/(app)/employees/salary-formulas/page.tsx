"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { DataTable } from "@/components/erp/data-table";
import { PageHeader } from "@/components/erp/page-header";
import { MODE_LABEL, summarize } from "@/components/salary/shared";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/input";
import { Badge, Card, Label } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { Formula } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function FormulasPage() {
  const can = useCan();
  const [inactive, setInactive] = useState(false);
  const q = useQuery({ queryKey: ["comp-formulas", inactive], queryFn: () => api.get<Formula[]>("/comp-formulas", { include_inactive: inactive }) });

  const columns: ColumnDef<Formula, unknown>[] = [
    {
      header: "Formula",
      accessorKey: "name",
      cell: ({ row }) => (
        <Link href={`/employees/salary-formulas/${row.original.id}`} className="font-medium hover:underline">
          {row.original.name}
          {!row.original.is_active && <Badge variant="muted" className="ml-2">Inactive</Badge>}
        </Link>
      ),
    },
    { header: "Type", id: "mode", cell: ({ row }) => MODE_LABEL[row.original.current?.definition.rate_schedule.mode ?? ""] ?? "—" },
    { header: "Rules (current version)", id: "rules", cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.current ? summarize(row.original.current.definition) : "—"}</span> },
    { header: "Version", id: "version", cell: ({ row }) => row.original.current ? `v${row.original.current.version_no} since ${formatDate(row.original.current.effective_from)}` : "—" },
    { header: "Employees", accessorKey: "employees_assigned", cell: ({ row }) => <span className="tabular">{row.original.employees_assigned}</span> },
  ];

  return (
    <>
      <PageHeader
        title="Salary formulas"
        description="How salary is calculated from the revenue credited to each employee in a salary period. Changing a formula adds a version from a date, so past periods keep their numbers."
        actions={can("comp_formulas.manage") && (
          <Button asChild><Link href="/employees/salary-formulas/new"><Plus /> New formula</Link></Button>
        )}
      />
      <div className="mb-3 flex items-center gap-2">
        <Checkbox id="inactive" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
        <Label htmlFor="inactive">Show inactive</Label>
      </div>
      <Card>
        <DataTable columns={columns} data={q.data} isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()} getRowId={(f) => f.id} />
      </Card>
    </>
  );
}
