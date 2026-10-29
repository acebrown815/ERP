"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { NAV, activeHref, canSee, type NavItem, type NavSection } from "@/lib/nav";
import { useMe } from "@/lib/session";
import { cn } from "@/lib/utils";

const OPEN_KEY = "nav.open";

function readOpen(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function writeOpen(open: string[]) {
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify(open));
  } catch {
    /* storage unavailable: groups still toggle for this page view */
  }
}

const rowClass = "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground transition-colors hover:bg-sidebar-active hover:text-white";

function ItemLink({ item, active, onNavigate }: { item: NavItem; active: boolean; onNavigate?: () => void }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(rowClass, active && "bg-sidebar-active font-medium text-white", item.phase && "text-sidebar-muted")}
    >
      <Icon className={cn("size-4 shrink-0", active ? "text-primary" : "text-sidebar-muted")} aria-hidden />
      <span className="truncate">{item.label}</span>
      {item.phase && <span className="ml-auto rounded border border-sidebar-border px-1 text-[10px] text-sidebar-muted">P{item.phase}</span>}
    </Link>
  );
}

/** Collapsed rail: one icon per link or group; a group opens its pages in a flyout. */
function RailEntry({ section, items, current, onNavigate }: { section: NavSection; items: NavItem[]; current?: string; onNavigate?: () => void }) {
  const railClass = (active: boolean) =>
    cn(
      "flex size-10 items-center justify-center rounded-md text-sidebar-muted transition-colors hover:bg-sidebar-active hover:text-white",
      active && "bg-sidebar-active text-white",
    );
  if (section.flat) {
    return items.map((item) => {
      const Icon = item.icon;
      return (
        <Link key={item.href} href={item.href} onClick={onNavigate} title={item.label} aria-label={item.label}
          aria-current={item.href === current ? "page" : undefined} className={railClass(item.href === current)}>
          <Icon className="size-5" aria-hidden />
        </Link>
      );
    });
  }
  const Icon = section.icon;
  const containsActive = items.some((i) => i.href === current);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger title={section.label} aria-label={section.label} className={railClass(containsActive)}>
        <Icon className="size-5" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="start" sideOffset={8}>
        <DropdownMenuLabel className="font-semibold text-foreground">{section.label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.map((item) => {
          const ItemIcon = item.icon;
          return (
            <DropdownMenuItem key={item.href} asChild className={cn(item.href === current && "bg-muted font-medium")}>
              <Link href={item.href} onClick={onNavigate}><ItemIcon /> {item.label}</Link>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Sidebar({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const me = useMe();
  const pathname = usePathname();
  const current = activeHref(pathname);
  const [open, setOpen] = useState<string[]>([]);

  // Restore the groups the user left open, and always open the group holding the current page.
  useEffect(() => {
    const holder = NAV.find((s) => !s.flat && s.items.some((i) => i.href === current))?.label;
    setOpen((prev) => {
      const base = prev.length ? prev : readOpen();
      return holder && !base.includes(holder) ? [...base, holder] : base;
    });
  }, [current]);

  const toggle = (label: string) =>
    setOpen((prev) => {
      const next = prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label];
      writeOpen(next);
      return next;
    });

  const sections = NAV.map((s) => ({ section: s, items: s.items.filter((i) => canSee(i, me.permissions)) })).filter((s) => s.items.length);

  if (collapsed) {
    return (
      <nav aria-label="Main" className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-3">
        {sections.map(({ section, items }) => (
          <RailEntry key={section.label} section={section} items={items} current={current} onNavigate={onNavigate} />
        ))}
      </nav>
    );
  }

  return (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-3">
      {sections.map(({ section, items }) => {
        if (section.flat) {
          return items.map((item) => <ItemLink key={item.href} item={item} active={item.href === current} onNavigate={onNavigate} />);
        }
        const isOpen = open.includes(section.label);
        const containsActive = items.some((i) => i.href === current);
        const Icon = section.icon;
        const id = `nav-${section.label.toLowerCase()}`;
        return (
          <div key={section.label} className="mt-1">
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={id}
              onClick={() => toggle(section.label)}
              className={cn(rowClass, "w-full font-medium", containsActive && !isOpen && "text-white")}
            >
              <Icon className={cn("size-4 shrink-0", containsActive ? "text-primary" : "text-sidebar-muted")} aria-hidden />
              <span className="truncate">{section.label}</span>
              <ChevronRight className={cn("ml-auto size-4 shrink-0 text-sidebar-muted transition-transform", isOpen && "rotate-90")} aria-hidden />
            </button>
            {isOpen && (
              <ul id={id} className="mb-1 ml-[1.15rem] mt-0.5 flex flex-col gap-0.5 border-l border-sidebar-border pl-2">
                {items.map((item) => (
                  <li key={item.href}>
                    <ItemLink item={item} active={item.href === current} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </nav>
  );
}
