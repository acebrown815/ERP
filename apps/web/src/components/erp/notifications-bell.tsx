"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import type { Notifications } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

/** Reminders, leave decisions and failed system checks. Polls every minute. */
export function NotificationsBell() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<Notifications>("/notifications"),
    refetchInterval: 60_000,
  });
  const read = useMutation({
    mutationFn: (ids?: string[]) => api.post("/notifications/read", { ids: ids ?? null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = q.data?.unread ?? 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"} className="relative">
          <Bell />
          {unread > 0 && (
            <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span className="font-medium text-foreground">Notifications</span>
          {unread > 0 && (
            <button type="button" className="text-xs text-primary hover:underline" onClick={() => read.mutate(undefined)}>Mark all read</button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {!q.data?.items.length ? (
          <p className="px-2 py-3 text-sm text-muted-foreground">Nothing yet.</p>
        ) : (
          q.data.items.slice(0, 12).map((n) => (
            <DropdownMenuItem key={n.id} asChild onSelect={() => !n.read_at && read.mutate([n.id])}>
              <Link href={n.link ?? "#"} className={cn("flex flex-col items-start gap-0.5", !n.read_at && "bg-accent/40")}>
                <span className={cn("text-sm", !n.read_at && "font-medium")}>{n.title}</span>
                {n.body && <span className="line-clamp-2 text-xs text-muted-foreground">{n.body}</span>}
                <span className="text-[11px] text-muted-foreground">{formatDateTime(n.created_at)}</span>
              </Link>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
