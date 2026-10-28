"use client";

import { Check, ChevronsUpDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export type ComboOption = { value: string; label: string; hint?: string };

/**
 * Searchable single-select. `options` can be filtered client-side, or pass `onSearch` to query the server.
 */
export function Combobox({
  id,
  value,
  onChange,
  options,
  selectedLabel,
  placeholder = "Select…",
  onSearch,
  disabled,
  invalid,
  clearable = true,
}: {
  id?: string;
  value: string | null;
  onChange: (value: string | null) => void;
  options: ComboOption[];
  selectedLabel?: string;
  placeholder?: string;
  onSearch?: (q: string) => void;
  disabled?: boolean;
  invalid?: boolean;
  clearable?: boolean;
}) {
  const autoId = useId();
  const listId = `${id ?? autoId}-list`;
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const visible = onSearch ? options : options.filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  const current = options.find((o) => o.value === value);
  const label = current?.label ?? selectedLabel;

  const pick = (v: string | null) => {
    onChange(v);
    setOpen(false);
    setQ("");
  };

  return (
    <div ref={root} className="relative">
      <button
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => {
          setOpen((o) => !o);
          setTimeout(() => input.current?.focus(), 0);
        }}
        className={cn(
          "flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-left text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          invalid && "border-destructive",
        )}
      >
        <span className={cn("truncate", !label && "text-muted-foreground")}>{label ?? placeholder}</span>
        <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
          {clearable && value && !disabled && (
            <X
              className="size-3.5 hover:text-foreground"
              aria-label="Clear"
              onClick={(e) => {
                e.stopPropagation();
                pick(null);
              }}
            />
          )}
          <ChevronsUpDown className="size-3.5" />
        </span>
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-56 rounded-md border bg-card shadow-lg">
          <input
            ref={input}
            value={q}
            placeholder="Search…"
            aria-label="Search"
            aria-controls={listId}
            className="w-full border-b bg-transparent px-3 py-2 text-sm outline-none"
            onChange={(e) => {
              setQ(e.target.value);
              setActive(0);
              onSearch?.(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, visible.length - 1));
              else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
              else if (e.key === "Enter") {
                e.preventDefault();
                const o = visible[active];
                if (o) pick(o.value);
              } else if (e.key === "Escape") setOpen(false);
            }}
          />
          <ul id={listId} role="listbox" className="max-h-64 overflow-y-auto p-1">
            {visible.length === 0 && <li className="px-2 py-1.5 text-sm text-muted-foreground">No matches</li>}
            {visible.map((o, i) => (
              <li
                key={o.value}
                role="option"
                aria-selected={o.value === value}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o.value);
                }}
                className={cn(
                  "flex cursor-default items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-sm",
                  i === active && "bg-muted",
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate">{o.label}</span>
                  {o.hint && <span className="block truncate text-xs text-muted-foreground">{o.hint}</span>}
                </span>
                {o.value === value && <Check className="size-4 shrink-0" />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
