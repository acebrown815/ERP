"use client";

import { useState } from "react";

import { EmployeeBidding, ProfileForm } from "@/components/bidding/employee-view";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/misc";
import { useProfile } from "@/lib/bidding";
import { cn } from "@/lib/utils";

type Tab = "overview" | "profile";

export default function MyBiddingPage() {
  const profile = useProfile();
  const [tab, setTab] = useState<Tab | null>(null);
  // Open on the Profile tab until a profile name is set.
  const current: Tab = tab ?? (profile.data && !profile.data.profile_names.length ? "profile" : "overview");
  const names = profile.data?.profile_names ?? [];
  const tabs = (
    <div className="inline-flex w-fit rounded-md border bg-card p-0.5" role="tablist">
      {(["overview", "profile"] as const).map((t) => (
        <Button key={t} role="tab" aria-selected={current === t} variant="ghost" size="sm" className={cn("capitalize", current === t && "bg-muted")} onClick={() => setTab(t)}>
          {t}
        </Button>
      ))}
    </div>
  );
  const overview = !profile.isError && !!profile.data && current === "overview";

  return (
    <>
      <PageHeader
        title="My Bidding"
        description={names.length ? `Your bids from ${names.map((n) => `“${n}”`).join(", ")} in the bids sheet.` : "Your bids, read live from your tabs in the bids sheet."}
      />
      {!overview && <div className="mb-4">{tabs}</div>}
      {profile.isError ? (
        <ErrorState error={profile.error} onRetry={() => profile.refetch()} />
      ) : !profile.data ? (
        <TableSkeleton />
      ) : current === "profile" ? (
        <Card className="max-w-2xl">
          <CardHeader>
            <CardTitle>Bidding profile names</CardTitle>
            <CardDescription>The extension writes your bids to a tab with this name. The ERP reads those tabs to build these pages, adding your profiles together.</CardDescription>
          </CardHeader>
          <CardContent>
            <ProfileForm profile={profile.data} path="/bidding/me/profile" onSaved={() => setTab("profile")} />
          </CardContent>
        </Card>
      ) : (
        <EmployeeBidding employeeId={profile.data.employee_id} onSetProfile={() => setTab("profile")} leading={tabs} />
      )}
    </>
  );
}
