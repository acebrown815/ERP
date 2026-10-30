"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useEmployees } from "@/lib/queries";

export type OwnerSelection = { employeeIds: string[]; unassigned: boolean };

function Option({ checked, onToggle, children }: { checked: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <DropdownMenuPrimitive.CheckboxItem
      checked={checked}
      // Keep the menu open so several can be ticked in one go.
      onSelect={(e) => e.preventDefault()}
      onCheckedChange={onToggle}
      className="flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted"
    >
      <span className="flex size-4 items-center justify-center rounded-sm border">{checked && <Check className="size-3" />}</span>
      {children}
    </DropdownMenuPrimitive.CheckboxItem>
  );
}

/** Whole company (nothing ticked), or any mix of employees and the part nobody carries ("Not assigned"). */
export function OwnerSelect({ value, onChange }: { value: OwnerSelection; onChange: (v: OwnerSelection) => void }) {
  const { data: employees = [] } = useEmployees();
  const names = employees.filter((e) => value.employeeIds.includes(e.id)).map((e) => e.full_name);
  const count = value.employeeIds.length + (value.unassigned ? 1 : 0);
  const label = count === 0 ? "Whole company" : count === 1 ? (value.unassigned ? "Not assigned" : names[0] ?? "1 employee") : `${count} selected`;
  const toggle = (id: string) =>
    onChange({ ...value, employeeIds: value.employeeIds.includes(id) ? value.employeeIds.filter((x) => x !== id) : [...value.employeeIds, id] });

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className="w-56 justify-between font-normal" aria-label="Show for">
          <span className="truncate">{label}</span>
          <ChevronDown className="opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="max-h-96 w-64 overflow-y-auto">
        <DropdownMenuItem disabled={count === 0} onSelect={() => onChange({ employeeIds: [], unassigned: false })}>
          Whole company
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <Option checked={value.unassigned} onToggle={() => onChange({ ...value, unassigned: !value.unassigned })}>
          <span>
            Not assigned
            <span className="block text-xs text-muted-foreground">Company income and expenses nobody carries</span>
          </span>
        </Option>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Employees</DropdownMenuLabel>
        {employees.map((e) => (
          <Option key={e.id} checked={value.employeeIds.includes(e.id)} onToggle={() => toggle(e.id)}>
            <span className="truncate">
              {e.full_name}
              {e.status === "terminated" && <span className="text-muted-foreground"> (left)</span>}
            </span>
          </Option>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
