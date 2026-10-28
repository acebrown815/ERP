"use client";

import Link from "next/link";

import { PageHeader } from "@/components/erp/page-header";
import { PaymentEntryEditor } from "@/components/payments/entry-editor";

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
      <PaymentEntryEditor />
    </>
  );
}
