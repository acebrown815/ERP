"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, LockOpen } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge, Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { Period } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const label = (p: Period) =>
  new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${p.start_date}T00:00:00Z`));

export default function PeriodsPage() {
  const qc = useQueryClient();
  const can = useCan();
  const periods = useQuery({ queryKey: ["periods"], queryFn: () => api.get<Period[]>("/accounting-periods") });
  const [reopening, setReopening] = useState<Period | null>(null);
  const [reason, setReason] = useState("");
  const today = new Date().toISOString().slice(0, 10);

  const act = useMutation({
    mutationFn: ({ p, action }: { p: Period; action: "close" | "reopen" }) =>
      api.post<Period>(`/accounting-periods/${p.id}/${action}`, { reason: action === "reopen" ? reason : null }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["periods"] });
      toast.success(`${label(p)} ${p.status === "closed" ? "closed" : "reopened"}`);
      setReopening(null);
      setReason("");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not update"),
  });

  if (periods.isError) return <ErrorState error={periods.error} onRetry={() => periods.refetch()} />;
  return (
    <>
      <PageHeader title="Accounting periods" description="Close a month once its books are checked: nothing can be posted, cancelled or reversed in a closed month until it is reopened." />
      <Card>
        {!periods.data ? <TableSkeleton /> : (
          <ul className="divide-y">
            {periods.data.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div className="flex items-center gap-3">
                  {p.status === "closed" ? <Lock className="size-4 text-muted-foreground" /> : <LockOpen className="size-4 text-success" />}
                  <span className="font-medium">{label(p)}</span>
                  {p.status === "closed" ? <Badge variant="muted">Closed {formatDateTime(p.closed_at)}</Badge> : <Badge variant="success">Open</Badge>}
                </div>
                {p.status === "open" && can("periods.close") && p.end_date < today && (
                  <Button variant="outline" size="sm" loading={act.isPending} onClick={() => act.mutate({ p, action: "close" })}>Close period</Button>
                )}
                {p.status === "closed" && can("periods.reopen") && (
                  <Button variant="ghost" size="sm" onClick={() => setReopening(p)}>Reopen</Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {reopening && (
        <Dialog open onOpenChange={(o) => !o && setReopening(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reopen {label(reopening)}?</DialogTitle>
              <DialogDescription>Postings and cancellations dated in this month become possible again. The reason is kept in the audit log.</DialogDescription>
            </DialogHeader>
            <FormField id="reopen_reason" label="Reason" required><Input id="reopen_reason" value={reason} onChange={(e) => setReason(e.target.value)} /></FormField>
            <DialogFooter>
              <Button variant="outline" onClick={() => setReopening(null)}>Cancel</Button>
              <Button disabled={reason.trim().length < 3} loading={act.isPending} onClick={() => act.mutate({ p: reopening, action: "reopen" })}>Reopen</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
