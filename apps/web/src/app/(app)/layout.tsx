"use client";

import type { ReactNode } from "react";

import { AppShell } from "@/components/erp/app-shell";
import { ErrorState } from "@/components/erp/states";
import { Skeleton } from "@/components/ui/misc";
import { SessionProvider, useMeQuery } from "@/lib/session";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const me = useMeQuery();

  if (me.isError) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <ErrorState error={me.error} onRetry={() => me.refetch()} />
      </div>
    );
  }
  if (!me.data) {
    return (
      <div className="flex min-h-dvh">
        <div className="hidden w-64 bg-sidebar lg:block" />
        <div className="flex-1 space-y-4 p-8">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    );
  }
  return (
    <SessionProvider me={me.data}>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
