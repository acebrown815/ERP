"use client";

import { ChevronDown, KeyRound, LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen, Sun, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { ChangePasswordDialog } from "@/components/erp/change-password-dialog";
import { NotificationsBell } from "@/components/erp/notifications-bell";
import { Sidebar } from "@/components/erp/sidebar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/misc";
import { useLogout, useMe } from "@/lib/session";
import { LOGO, SITE_NAME } from "@/lib/site";
import { cn } from "@/lib/utils";

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => {
        const next = !dark;
        document.documentElement.classList.toggle("dark", next);
        try {
          localStorage.setItem("theme", next ? "dark" : "light");
        } catch {
          /* storage unavailable: theme still applies for this page view */
        }
        setDark(next);
      }}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

function UserMenu() {
  const me = useMe();
  const logout = useLogout();
  const [pwOpen, setPwOpen] = useState(false);
  const initials = me.full_name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" className="gap-2 px-2">
            <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              {initials}
            </span>
            <span className="hidden text-sm sm:inline">{me.full_name}</span>
            <ChevronDown className="text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel>
            <div className="font-medium text-foreground">{me.full_name}</div>
            <div>{me.email}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {me.roles.map((r) => (
                <Badge key={r.id} variant="muted">
                  {r.name}
                </Badge>
              ))}
            </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setPwOpen(true)}>
            <KeyRound /> Change password
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void logout()}>
            <LogOut /> Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ChangePasswordDialog open={pwOpen} onOpenChange={setPwOpen} />
    </>
  );
}

const COLLAPSED_KEY = "nav.collapsed";

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/dashboard" title={SITE_NAME}
      className={cn("flex h-14 shrink-0 items-center gap-2 font-semibold text-white", compact ? "justify-center" : "px-5")}>
      {/* eslint-disable-next-line @next/next/no-img-element -- small static logo, no optimisation needed */}
      <img src={LOGO} alt="" width={28} height={28} className="size-7 shrink-0 rounded-full bg-white" />
      {!compact && <span className="truncate">{SITE_NAME}</span>}
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  // Desktop only: the sidebar shrinks to an icon rail. Remembered per browser.
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "1");
    } catch {
      /* storage unavailable: start expanded */
    }
  }, []);
  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      /* storage unavailable: applies for this page view */
    }
  };
  const brand = <Brand />;

  return (
    <div className="flex min-h-dvh">
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 lg:flex",
          collapsed ? "w-16" : "w-64",
        )}
      >
        <div className="border-b border-sidebar-border"><Brand compact={collapsed} /></div>
        <Sidebar collapsed={collapsed} />
        <div className={cn("flex shrink-0 border-t border-sidebar-border p-2", collapsed ? "justify-center" : "justify-end")}>
          <Button
            variant="ghost"
            size="icon"
            className="text-sidebar-muted hover:bg-sidebar-active hover:text-white"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleCollapsed}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </Button>
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-sidebar">
            <div className="flex items-center justify-between border-b border-sidebar-border pr-3">
              {brand}
              <Button
                variant="ghost"
                size="icon"
                className="text-sidebar-foreground hover:bg-sidebar-active"
                aria-label="Close navigation"
                onClick={() => setMobileOpen(false)}
              >
                <X />
              </Button>
            </div>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-2 border-b bg-background/90 px-4 backdrop-blur lg:px-8">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>
            <Menu />
          </Button>
          <div className="flex-1" />
          <NotificationsBell />
          <ThemeToggle />
          <UserMenu />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
