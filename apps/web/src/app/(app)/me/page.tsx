"use client";

import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/erp/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/erp/states";
import { EmployeeSalaryView } from "@/components/salary/employee-salary";
import { Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { Employee } from "@/lib/types";

/** Employee self-service (Q10): own revenue, formula, calculated and paid salary. Read-only. */
export default function MyPage() {
  const can = useCan();
  const me = useQuery({ queryKey: ["employee", "me"], queryFn: () => api.get<Employee>("/employees/me"), retry: false });
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 404) {
      return (
        <>
          <PageHeader title="My salary" />
          <Card><EmptyState title="Your sign-in isn't linked to an employee" description="Ask an administrator to link your account to your employee record." /></Card>
        </>
      );
    }
    return <ErrorState error={me.error} onRetry={() => me.refetch()} />;
  }
  if (!me.data) return <TableSkeleton />;
  return (
    <>
      <PageHeader
        title="My salary"
        description="Revenue credited to you, how your salary is calculated, and what has been paid. Figures for the current period update as customer payments come in."
      />
      {can("salary.read") ? (
        <EmployeeSalaryView employeeId={me.data.id} path="/me/salary" showRevenue={can("revenue.read")} />
      ) : (
        <Card><EmptyState title="Salary isn't visible to your role" /></Card>
      )}
    </>
  );
}
