"use client";

import { Construction } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/misc";
import { findNavItem } from "@/lib/nav";

// Screens listed in the navigation that ship in a later phase land here.
export default function PlannedPage() {
  const pathname = usePathname();
  const item = findNavItem(pathname);

  if (!item) {
    return (
      <Card className="mx-auto mt-12 max-w-md p-8 text-center">
        <h1 className="text-lg font-semibold">Page not found</h1>
        <p className="mt-1 text-sm text-muted-foreground">There is nothing at {pathname}.</p>
        <Button asChild className="mt-4">
          <Link href="/dashboard">Back to dashboard</Link>
        </Button>
      </Card>
    );
  }
  return (
    <Card className="mx-auto mt-12 max-w-md p-8 text-center">
      <Construction className="mx-auto size-8 text-muted-foreground" aria-hidden />
      <h1 className="mt-3 text-lg font-semibold">{item.label}</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        This screen is planned for Phase {item.phase}. The design is in docs/architecture.md.
      </p>
      <Button asChild variant="outline" className="mt-4">
        <Link href="/dashboard">Back to dashboard</Link>
      </Button>
    </Card>
  );
}
