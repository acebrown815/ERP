"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";

import { PageHeader } from "@/components/erp/page-header";
import { ErrorState } from "@/components/erp/states";
import { PaymentEntryEditor } from "@/components/payments/entry-editor";
import { PaymentEntryView, StatusBadge } from "@/components/payments/entry-view";
import { Skeleton } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { PaymentEntry } from "@/lib/types";

export default function PaymentEntryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const can = useCan();
  const entry = useQuery({ queryKey: ["payment-entry", id], queryFn: () => api.get<PaymentEntry>(`/payment-entries/${id}`) });

  if (entry.isError) return <ErrorState error={entry.error} onRetry={() => entry.refetch()} />;
  if (!entry.data) return <Skeleton className="h-96 w-full" />;
  const e = entry.data;
  const editable = e.status === "draft" && can("payments.create");

  return (
    <>
      <PageHeader
        title={e.number}
        description={
          <span className="flex items-center gap-2">
            <StatusBadge status={e.status} />
            <Link href="/accounting/payment-entries" className="text-primary hover:underline">
              All payments
            </Link>
          </span>
        }
      />
      {/* key: remount the editor when a new version arrives, so it starts from the saved state */}
      {editable ? <PaymentEntryEditor key={`${e.id}-${e.version}`} entry={e} /> : <PaymentEntryView entry={e} />}
    </>
  );
}
