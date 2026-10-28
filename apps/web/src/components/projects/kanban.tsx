"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CornerDownRight, MessageSquare, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import type { Page, Task, Timeline } from "@/lib/types";
import { rankBetween } from "@/lib/rank";
import { cn, formatDate } from "@/lib/utils";

import { isOverdue, PriorityLabel, TASK_STATUSES } from "./shared";
import { TaskPanel } from "./task-panel";

type Drop = { status: string; index: number };

/**
 * Kanban for one project: columns are statuses, order is the task's board rank. Dragging a card sends one
 * move request with its new neighbours, so only that card is rewritten (docs/architecture.md, Section 11.2).
 */
export function KanbanBoard({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const key = ["tasks", "board", projectId];
  const tasks = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<Page<Task>>("/tasks", { project_id: projectId, page_size: 500 })).items,
  });
  const timeline = useQuery({ queryKey: ["timeline", projectId], queryFn: () => api.get<Timeline>(`/projects/${projectId}/timeline`) });
  const canCreate = !!timeline.data?.can_edit;
  const [dragging, setDragging] = useState<Task | null>(null);
  const [drop, setDrop] = useState<Drop | null>(null);
  const [open, setOpen] = useState<{ taskId?: string; status?: string } | null>(null);

  const columns = TASK_STATUSES.map((s) => ({
    ...s,
    tasks: (tasks.data ?? []).filter((t) => t.status === s.key).sort((a, b) => (a.board_rank < b.board_rank ? -1 : 1)),
  }));

  const move = useMutation({
    mutationFn: ({ task, status, before, after }: { task: Task; status: string; before?: Task; after?: Task }) =>
      api.post<Task>(`/tasks/${task.id}/move`, { version: task.version, status, before_id: before?.id ?? null, after_id: after?.id ?? null }),
    onMutate: async ({ task, status, before, after }) => {
      // Optimistic: put the card where it was dropped until the server answers.
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<Task[]>(key);
      const col = (previous ?? []).filter((t) => t.status === status && t.id !== task.id).sort((x, y) => (x.board_rank < y.board_rank ? -1 : 1));
      const rank = rankBetween(before?.board_rank ?? (after ? null : col.at(-1)?.board_rank), after?.board_rank);
      qc.setQueryData<Task[]>(key, (list) => list?.map((t) => (t.id === task.id ? { ...t, status, board_rank: rank } : t)));
      return { previous };
    },
    onError: (err, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(key, ctx.previous);
      toast.error(err instanceof ApiError ? err.message : "Could not move the task");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["timeline", projectId] });
      qc.invalidateQueries({ queryKey: ["task-progress"] });
    },
  });

  const onDrop = () => {
    if (!dragging || !drop) return;
    const col = columns.find((c) => c.key === drop.status)!.tasks.filter((t) => t.id !== dragging.id);
    const before = col[drop.index - 1];
    const after = col[drop.index];
    const unchanged = dragging.status === drop.status && columns.find((c) => c.key === drop.status)!.tasks.indexOf(dragging) === drop.index;
    if (!unchanged) move.mutate({ task: dragging, status: drop.status, before, after });
    setDragging(null);
    setDrop(null);
  };

  if (tasks.isError) return <p className="text-sm text-destructive">Could not load tasks.</p>;
  return (
    <>
      <div className="grid gap-3 overflow-x-auto pb-2 md:grid-cols-5" onDragEnd={() => { setDragging(null); setDrop(null); }}>
        {columns.map((col) => (
          <div
            key={col.key}
            className={cn("flex min-h-48 min-w-56 flex-col rounded-lg border bg-muted/40", drop?.status === col.key && "ring-2 ring-primary/40")}
            onDragOver={(e) => {
              if (!dragging) return;
              e.preventDefault();
              if (drop?.status !== col.key || e.target === e.currentTarget) setDrop({ status: col.key, index: col.tasks.filter((t) => t.id !== dragging.id).length });
            }}
            onDrop={(e) => {
              e.preventDefault();
              onDrop();
            }}
          >
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-sm font-medium">{col.label}</span>
              <span className="tabular text-xs text-muted-foreground">{col.tasks.length}</span>
            </div>
            <ul className="flex flex-1 flex-col gap-2 px-2 pb-2">
              {col.tasks.map((t, i) => {
                const overdue = isOverdue(t.due_date, t.status);
                const showMarker = drop?.status === col.key && dragging && dragging.id !== t.id && col.tasks.filter((x) => x.id !== dragging.id).indexOf(t) === drop.index;
                return (
                  <li key={t.id}>
                    {showMarker && <div className="mb-2 h-0.5 rounded bg-primary" aria-hidden />}
                    <button
                      type="button"
                      draggable={t.can_move}
                      onDragStart={(e) => {
                        setDragging(t);
                        e.dataTransfer.effectAllowed = "move";
                        e.dataTransfer.setData("text/plain", t.id);
                      }}
                      onDragOver={(e) => {
                        if (!dragging) return;
                        e.preventDefault();
                        e.stopPropagation();
                        const box = e.currentTarget.getBoundingClientRect();
                        const others = col.tasks.filter((x) => x.id !== dragging.id);
                        const at = others.indexOf(t);
                        if (at < 0) return;
                        setDrop({ status: col.key, index: e.clientY > box.top + box.height / 2 ? at + 1 : at });
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        onDrop();
                      }}
                      onClick={() => setOpen({ taskId: t.id })}
                      className={cn(
                        "w-full rounded-md border bg-card p-2.5 text-left text-sm shadow-sm transition hover:border-primary/40",
                        t.can_move && "cursor-grab active:cursor-grabbing",
                        dragging?.id === t.id && "opacity-40",
                      )}
                      aria-label={`${t.number} ${t.title}, ${col.label}. Open details`}
                    >
                      {t.parent_task_id && <CornerDownRight className="mb-0.5 inline size-3 text-muted-foreground" aria-label="Subtask" />}{" "}
                      <span className={cn(t.status === "done" && "text-muted-foreground line-through")}>{t.title}</span>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                        <span className="font-mono">{t.number}</span>
                        <PriorityLabel priority={t.priority} />
                        {t.due_date && (
                          <span className={cn("flex items-center gap-0.5", overdue && "font-medium text-destructive")}>
                            <CalendarClock className="size-3" /> {formatDate(t.due_date)}
                          </span>
                        )}
                        {t.subtasks > 0 && <span>{t.subtasks_done}/{t.subtasks} sub</span>}
                      </div>
                      {t.assignees.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {t.assignees.map((a) => (
                            <span key={a.id} className="rounded-full bg-accent px-1.5 py-0.5 text-[11px] text-accent-foreground">{a.name}</span>
                          ))}
                        </div>
                      )}
                    </button>
                    {i === col.tasks.length - 1 && drop?.status === col.key && dragging && drop.index >= col.tasks.filter((x) => x.id !== dragging.id).length && dragging.id !== t.id && (
                      <div className="mt-2 h-0.5 rounded bg-primary" aria-hidden />
                    )}
                  </li>
                );
              })}
            </ul>
            {canCreate && (
              <Button variant="ghost" size="sm" className="m-1 justify-start text-muted-foreground" onClick={() => setOpen({ status: col.key })}>
                <Plus /> Add task
              </Button>
            )}
          </div>
        ))}
      </div>
      <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
        <MessageSquare className="size-3" /> Drag cards to change status or order; click a card for details, time and comments.
      </p>
      {open && (
        <TaskPanel
          key={open.taskId ?? `new-${open.status}`}
          projectId={projectId}
          taskId={open.taskId}
          defaultStatus={open.status}
          onClose={() => setOpen(null)}
          onOpenTask={(id) => setOpen({ taskId: id })}
        />
      )}
    </>
  );
}
