"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";

import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { SystemChecks } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export default function SystemChecksPage() {
  const q = useQuery({ queryKey: ["system-checks"], queryFn: () => api.get<SystemChecks>("/system/checks"), staleTime: 0 });
  return (
    <>
      <PageHeader
        title="System checks"
        description="Consistency checks over the books and records. They also run every night; administrators get a notification if one fails."
        actions={<Button variant="outline" loading={q.isFetching} onClick={() => q.refetch()}><RefreshCw /> Run again</Button>}
      />
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <TableSkeleton rows={6} /> : (
        <Card>
          <CardContent className="flex flex-col gap-1 pt-6">
            <p className="mb-3 flex items-center gap-2 text-sm">
              {q.data.ok ? <Badge variant="success">All checks passed</Badge> : <Badge variant="destructive">{q.data.checks.filter((c) => !c.ok).length} failed</Badge>}
              <span className="text-muted-foreground">Ran {formatDateTime(q.data.ran_at)}</span>
            </p>
            <ul className="divide-y">
              {q.data.checks.map((c) => (
                <li key={c.key} className="flex items-start gap-3 py-3">
                  {c.ok ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-label="Passed" /> : <XCircle className="mt-0.5 size-5 shrink-0 text-destructive" aria-label="Failed" />}
                  <div>
                    <p className="text-sm font-medium">{c.label}</p>
                    <p className="text-sm text-muted-foreground">{c.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      <p className="mt-3 text-xs text-muted-foreground">Backups, restore drills and monitoring are described in docs/operations.md.</p>
    </>
  );
}
