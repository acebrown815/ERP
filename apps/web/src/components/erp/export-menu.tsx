"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

const FORMATS = [
  { key: "csv", label: "CSV (exact decimals)" },
  { key: "xlsx", label: "Excel (.xlsx)" },
  { key: "pdf", label: "PDF" },
] as const;

/** Download a report as CSV, Excel or PDF: same columns and totals as on screen. `path` is under /api/v1. */
export function ExportMenu({ path, params = {}, label = "Export", formats }: { path: string; params?: Record<string, string | undefined | null>; label?: string; formats?: (typeof FORMATS)[number]["key"][] }) {
  const href = (format: string) => {
    const qs = new URLSearchParams(Object.entries({ ...params, format }).filter(([, v]) => v) as [string, string][]);
    return `/api/v1${path}?${qs}`;
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline"><Download /> {label}</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {FORMATS.filter((f) => !formats || formats.includes(f.key)).map((f) => (
          <DropdownMenuItem key={f.key} asChild>
            <a href={href(f.key)} download>{f.label}</a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
