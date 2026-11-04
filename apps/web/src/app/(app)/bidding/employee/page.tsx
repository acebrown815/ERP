"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, IdCard } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EmployeeBidding } from "@/components/bidding/employee-view";
import { PageHeader } from "@/components/erp/page-header";
import { EmptyState } from "@/components/erp/states";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { EmployeeDetail } from "@/lib/types";

/** /bidding/employee?id=… : one employee's bidding, for people who see everyone's (bidding.read "all"). */
function EmployeeBiddingPage() {
  const id = useSearchParams().get("id");
  const employee = useQuery({ queryKey: ["employee", id], queryFn: () => api.get<EmployeeDetail>(`/employees/${id}`), enabled: !!id, retry: false });
  if (!id) return <EmptyState title="No employee chosen" action={<Button asChild variant="outline"><Link href="/bidding">Team overview</Link></Button>} />;
  const e = employee.data;
  return (
    <>
      <PageHeader
        title={e ? `${e.full_name}: bidding` : "Employee bidding"}
        description={e?.bidding_profile_names.length ? `Sheet tabs: ${e.bidding_profile_names.join(", ")}` : undefined}
        actions={
          <>
            {e && <Button variant="outline" asChild><Link href={`/employees/${id}`}><IdCard /> Profile</Link></Button>}
            <Button variant="outline" asChild><Link href="/bidding"><ArrowLeft /> Team overview</Link></Button>
          </>
        }
      />
      <EmployeeBidding employeeId={id} />
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <EmployeeBiddingPage />
    </Suspense>
  );
}
