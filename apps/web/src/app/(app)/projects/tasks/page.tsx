"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader } from "@/components/erp/page-header";
import { TableSkeleton } from "@/components/erp/states";
import { isOverdue, PriorityLabel, TASK_STATUSES, TaskStatusBadge } from "@/components/projects/shared";
import { TaskPanel } from "@/components/projects/task-panel";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useCan } from "@/lib/session";
import { formatAmount } from "@/lib/money";
import type { Page, Task } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const OPEN = ["backlog", "todo", "in_progress", "review"];

/** Tasks across projects: everything I can see by default, or only mine (?who=me opens it that way). */
function TasksList() {
  const [who, setWho] = useState<"me" | "all">(useSearchParams().get("who") === "me" ? "me" : "all");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Task | null>(null);
  const [creating, setCreating] = useState(false);
  const can = useCan();
  const tasks = useQuery({
    queryKey: ["tasks", "cross", who, status, q],
    queryFn: async () => {
      const params = new URLSearchParams([["page_size", "500"]]);
      if (who === "me") params.append("assignee", "me");
      for (const s of status === "open" ? OPEN : status ? [status] : []) params.append("status", s);
      if (q) params.append("q", q);
      return (await api.get<Page<Task>>(`/tasks?${params}`)).items;
    },
    placeholderData: keepPreviousData,
  });
  const rows = [...(tasks.data ?? [])].sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
  return (
    <>
      <PageHeader
        title="Tasks"
        description="Tasks across your projects, soonest due first. Click one for details, time and comments."
        actions={(can("tasks.manage") || can("projects.create_own")) && <Button onClick={() => setCreating(true)}><Plus /> New task</Button>}
      />
      <Card>
        <div className="flex flex-col gap-2 border-b p-3 sm:flex-row">
          <Select aria-label="Whose tasks" className="sm:w-44" value={who} onChange={(e) => setWho(e.target.value as "me" | "all")}>
            <option value="me">Assigned to me</option>
            <option value="all">All I can see</option>
          </Select>
          <Select aria-label="Status" className="sm:w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Open</option>
            <option value="">All statuses</option>
            {TASK_STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </Select>
          <Input aria-label="Search" placeholder="Search" className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {!tasks.data ? <TableSkeleton /> : rows.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">{who === "me" ? "Nothing assigned to you." : "No tasks."}</p>
        ) : (
          <Table>
            <THead><TR><TH>Task</TH><TH>Project</TH><TH>Status</TH><TH>Assignees</TH><TH>Due</TH><TH className="text-right">Hours</TH></TR></THead>
            <TBody>
              {rows.map((t) => (
                <TR key={t.id} className="cursor-pointer" onClick={() => setOpen(t)}>
                  <TD><span className="font-medium">{t.title}</span><span className="block font-mono text-xs text-muted-foreground">{t.number}</span></TD>
                  <TD className="text-sm">
                    <Link href={`/projects/${t.project_id}?tab=board`} className="hover:underline" onClick={(e) => e.stopPropagation()}>{t.project_name}</Link>
                  </TD>
                  <TD><TaskStatusBadge status={t.status} /> <PriorityLabel priority={t.priority} /></TD>
                  <TD className="text-sm">{t.assignees.map((a) => a.name).join(", ") || "—"}</TD>
                  <TD className={cn("text-sm", isOverdue(t.due_date, t.status) && "font-medium text-destructive")}>{formatDate(t.due_date)}</TD>
                  <TD className="tabular text-right text-sm">{formatAmount(t.logged_hours, 1)}{t.estimate_hours ? ` / ${formatAmount(t.estimate_hours, 1)}` : ""}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      {open && <TaskPanel key={open.id} projectId={open.project_id} taskId={open.id} onClose={() => setOpen(null)} />}
      {creating && <TaskPanel onClose={() => setCreating(false)} />}
    </>
  );
}

export default function TasksPage() {
  return (
    <Suspense>
      <TasksList />
    </Suspense>
  );
}
