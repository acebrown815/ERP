"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type MultiOption = { value: string; label: string; hint?: string; indent?: number };

/** A dropdown of checkboxes with a search box. Nothing ticked shows the placeholder ("Any …"). */
export function MultiSelect({
  options,
  value,
  onChange,
  placeholder,
  noun = "selected",
  className,
}: {
  options: MultiOption[];
  value: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
  noun?: string;
  className?: string;
}) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const shown = needle ? options.filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(needle)) : options;
  const first = options.find((o) => o.value === value[0]);
  const label = value.length === 0 ? placeholder : value.length === 1 ? first?.label ?? `1 ${noun}` : `${value.length} ${noun}`;
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);

  return (
    <DropdownMenu onOpenChange={(open) => !open && setQ("")}>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className={cn("w-full justify-between font-normal", value.length === 0 && "text-muted-foreground", className)}>
          <span className="truncate">{label}</span>
          <ChevronDown className="opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72 p-0">
        <div className="p-1.5">
          <Input
            aria-label="Search"
            placeholder="Search…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            // Keep typing in the box instead of the menu's type-to-jump.
            onKeyDown={(e) => e.key !== "Escape" && e.stopPropagation()}
          />
        </div>
        <div className="max-h-80 overflow-y-auto p-1">
          {value.length > 0 && (
            <>
              <DropdownMenuItem onSelect={() => onChange([])}>Clear ({value.length})</DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          {shown.length === 0 && <p className="px-2 py-1.5 text-sm text-muted-foreground">No matches</p>}
          {shown.map((o) => {
            const checked = value.includes(o.value);
            return (
              <DropdownMenuPrimitive.CheckboxItem
                key={o.value}
                checked={checked}
                // Keep the menu open so several can be ticked in one go.
                onSelect={(e) => e.preventDefault()}
                onCheckedChange={() => toggle(o.value)}
                className="flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted"
                style={!needle && o.indent ? { paddingLeft: `${0.5 + o.indent * 0.75}rem` } : undefined}
              >
                <span className="flex size-4 shrink-0 items-center justify-center rounded-sm border">{checked && <Check className="size-3" />}</span>
                <span className="truncate">{o.label}</span>
                {o.hint && <span className="ml-auto shrink-0 text-xs text-muted-foreground">{o.hint}</span>}
              </DropdownMenuPrimitive.CheckboxItem>
            );
          })}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
