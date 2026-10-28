"use client";

import { useQuery } from "@tanstack/react-query";

import { Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { Page, Project } from "@/lib/types";
import { cn } from "@/lib/utils";

export const TASK_STATUSES = [
  { key: "backlog", label: "Backlog" },
  { key: "todo", label: "To do" },
  { key: "in_progress", label: "In progress" },
  { key: "review", label: "Review" },
  { key: "done", label: "Done" },
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number]["key"];

export const STATUS_LABEL: Record<string, string> = Object.fromEntries(TASK_STATUSES.map((s) => [s.key, s.label]));

const STATUS_VARIANT: Record<string, "default" | "muted" | "warning" | "success"> = {
  backlog: "muted",
  todo: "default",
  in_progress: "warning",
  review: "warning",
  done: "success",
};

export function TaskStatusBadge({ status }: { status: string }) {
  return <Badge variant={STATUS_VARIANT[status] ?? "default"}>{STATUS_LABEL[status] ?? status}</Badge>;
}

const PRIORITY_CLASS: Record<string, string> = {
  low: "text-muted-foreground",
  medium: "text-foreground",
  high: "text-warning",
  urgent: "text-destructive font-medium",
};

export function PriorityLabel({ priority }: { priority: string }) {
  return <span className={cn("text-xs capitalize", PRIORITY_CLASS[priority])}>{priority}</span>;
}

/** 0–100 bar. Percent is a decimal string from the API; display only, so a float is fine. */
export function ProgressBar({ value, className }: { value: string | number; className?: string }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full rounded-full", pct >= 100 ? "bg-success" : "bg-primary")} style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular w-10 text-right text-xs text-muted-foreground">{Math.round(pct)}%</span>
    </div>
  );
}

export function useProjectList() {
  return useQuery({
    queryKey: ["projects", "all"],
    queryFn: async () => (await api.get<Page<Project>>("/projects", { page_size: 200 })).items,
  });
}

/** Project picker for the board / timeline pages (active ones first). */
export function ProjectSelect({ value, onChange }: { value: string | null; onChange: (id: string) => void }) {
  const projects = useProjectList();
  const list = [...(projects.data ?? [])].sort((a, b) => Number(b.status === "active") - Number(a.status === "active") || a.name.localeCompare(b.name));
  return (
    <Select aria-label="Project" className="w-auto min-w-64" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled>Choose a project…</option>
      {list.map((p) => (
        <option key={p.id} value={p.id}>{p.name} ({p.number}){p.status !== "active" ? ` · ${p.status.replace("_", " ")}` : ""}</option>
      ))}
    </Select>
  );
}

export function isOverdue(due: string | null | undefined, status: string): boolean {
  return !!due && status !== "done" && due < new Date().toISOString().slice(0, 10);
}
