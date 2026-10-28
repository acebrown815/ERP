"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/erp/page-header";
import { PaymentEntryEditor, type SalaryPrefill } from "@/components/payments/entry-editor";

function Editor() {
  // ?salary_employee=<id>&amount=<owed>&period=<salary period id>, from the salary board's "Pay".
  const params = useSearchParams();
  const employeeId = params.get("salary_employee");
  const salary: SalaryPrefill | undefined = employeeId
    ? { employeeId, amount: params.get("amount") ?? undefined, periodId: params.get("period") ?? undefined }
    : undefined;
  return <PaymentEntryEditor salary={salary} />;
}

export default function NewPaymentEntryPage() {
  return (
    <>
      <PageHeader
        title="New payment"
        description={
          <>
            Saved as a draft until you submit it. <Link href="/accounting/payment-entries" className="text-primary hover:underline">Back to list</Link>
          </>
        }
      />
      <Suspense>
        <Editor />
      </Suspense>
    </>
  );
}
