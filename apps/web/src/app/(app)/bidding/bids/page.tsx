"use client";

import { useQuery } from "@tanstack/react-query";

import { BidsTable, DataBar } from "@/components/bidding/shared";
import { PageHeader } from "@/components/erp/page-header";
import { Card } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { DataState } from "@/lib/bidding";

export default function AllBidsPage() {
  // Freshness for the header; the table loads its own rows.
  const data = useQuery({ queryKey: ["bidding", "bids", "state"], queryFn: async () => (await api.get<{ data: DataState }>("/bidding/bids", { page_size: 1 })).data });
  return (
    <>
      <PageHeader title="All bids" description="Every job applied to, from every employee's tab of the bids sheet." />
      <DataBar data={data.data} />
      <Card>
        <BidsTable />
      </Card>
    </>
  );
}
