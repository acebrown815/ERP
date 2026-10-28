"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Diamond } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import type { Timeline, TimelineTask } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

import { TaskPanel } from "./task-panel";

const DAY = 86_400_000;
const ROW = 34;
const HEADER = 44;
const ZOOMS = { Day: 34, Week: 14, Month: 5 } as const;
type Zoom = keyof typeof ZOOMS;

const toDay = (s: string) => Math.round(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / DAY);
const fromDay = (d: number) => new Date(d * DAY).toISOString().slice(0, 10);

type Row = { task: TimelineTask; depth: number };
type Drag = { id: string; mode: "move" | "start" | "end"; x0: number; start: number; end: number; dStart: number; dEnd: number };

/** Parents first, each followed by its subtasks; siblings by start date. */
function order(tasks: TimelineTask[]): Row[] {
  const byParent = new Map<string | null, TimelineTask[]>();
  const ids = new Set(tasks.map((t) => t.id));
  for (const t of tasks) {
    const p = t.parent_task_id && ids.has(t.parent_task_id) ? t.parent_task_id : null;
    byParent.set(p, [...(byParent.get(p) ?? []), t]);
  }
  const out: Row[] = [];
  const walk = (p: string | null, depth: number) => {
    for (const t of byParent.get(p) ?? []) {
      out.push({ task: t, depth });
      walk(t.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

/**
 * Gantt for one project (docs/architecture.md, Section 11.4). Drag a bar to move it, drag its ends to change the
 * start or due date; each change is one PATCH with a version check. Reads the same task rows as the board.
 */
export function Gantt({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["timeline", projectId], queryFn: () => api.get<Timeline>(`/projects/${projectId}/timeline`) });
  const [zoom, setZoom] = useState<Zoom>("Day");
  const [drag, setDrag] = useState<Drag | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const moved = useRef(false);
  const px = ZOOMS[zoom];

  const save = useMutation({
    mutationFn: ({ task, start, end }: { task: TimelineTask; start: number; end: number }) =>
      api.patch(`/tasks/${task.id}`, { version: task.version, start_date: fromDay(start), due_date: fromDay(end) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not move the task"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["timeline", projectId] }),
  });

  const t = q.data;
  const rows = useMemo(() => (t ? order(t.tasks) : []), [t]);
  const range = useMemo(() => {
    if (!t) return { from: 0, to: 0 };
    const days = [
      toDay(t.today),
      ...(t.start_date ? [toDay(t.start_date)] : []),
      ...(t.deadline ? [toDay(t.deadline)] : []),
      ...t.tasks.flatMap((x) => [x.start_date, x.due_date].filter(Boolean).map((d) => toDay(d!))),
      ...t.milestones.filter((m) => m.due_date).map((m) => toDay(m.due_date!)),
    ];
    return { from: Math.min(...days) - 3, to: Math.max(...days) + 10 };
  }, [t]);

  if (q.isError) return <p className="text-sm text-destructive">Could not load the timeline.</p>;
  if (!t) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const width = (range.to - range.from + 1) * px;
  const x = (day: number) => (day - range.from) * px;
  const today = toDay(t.today);
  const span = (task: TimelineTask): [number, number] | null => {
    if (drag?.id === task.id) return [drag.start + drag.dStart, drag.end + drag.dEnd];
    const s = task.start_date ? toDay(task.start_date) : task.due_date ? toDay(task.due_date) : null;
    const e = task.due_date ? toDay(task.due_date) : s;
    return s === null || e === null ? null : [s, e];
  };
  const index = new Map(rows.map((r, i) => [r.task.id, i]));

  // Header: months, then day numbers (or week starts) depending on zoom.
  const months: { label: string; from: number; to: number }[] = [];
  for (let d = range.from; d <= range.to; d++) {
    const label = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(d * DAY));
    const last = months.at(-1);
    if (last?.label === label) last.to = d;
    else months.push({ label, from: d, to: d });
  }
  const ticks: number[] = [];
  for (let d = range.from; d <= range.to; d++) {
    const date = new Date(d * DAY);
    if (zoom === "Day" || (zoom === "Week" && date.getUTCDay() === 1) || (zoom === "Month" && date.getUTCDate() === 1)) ticks.push(d);
  }

  const onPointerDown = (e: React.PointerEvent, task: TimelineTask, mode: Drag["mode"]) => {
    if (!t.can_edit) return;
    const s = span(task);
    if (!s) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    moved.current = false;
    setDrag({ id: task.id, mode, x0: e.clientX, start: s[0], end: s[1], dStart: 0, dEnd: 0 });
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const delta = Math.round((e.clientX - drag.x0) / px);
    if (delta !== 0) moved.current = true;
    if (drag.mode === "move") setDrag({ ...drag, dStart: delta, dEnd: delta });
    else if (drag.mode === "start") setDrag({ ...drag, dStart: Math.min(delta, drag.end - drag.start), dEnd: 0 });
    else setDrag({ ...drag, dStart: 0, dEnd: Math.max(delta, drag.start - drag.end) });
  };
  const onPointerUp = () => {
    if (!drag) return;
    const task = t.tasks.find((x) => x.id === drag.id)!;
    if (drag.dStart || drag.dEnd) save.mutate({ task, start: drag.start + drag.dStart, end: drag.end + drag.dEnd });
    setDrag(null);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1 rounded-md border p-0.5 text-sm" role="radiogroup" aria-label="Zoom">
          {(Object.keys(ZOOMS) as Zoom[]).map((z) => (
            <button key={z} type="button" role="radio" aria-checked={zoom === z} onClick={() => setZoom(z)}
              className={cn("rounded px-2.5 py-1", zoom === z ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground")}>
              {z}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="h-2.5 w-5 rounded-sm bg-primary/70" /> Task (fill = progress)</span>
          <span className="flex items-center gap-1"><span className="h-2.5 w-5 rounded-sm border-2 border-destructive" /> Delayed</span>
          <span className="flex items-center gap-1"><Diamond className="size-3 fill-warning text-warning" /> Milestone</span>
          <span className="flex items-center gap-1"><span className="h-3 w-0.5 bg-primary" /> Today</span>
          {t.deadline && <span className="flex items-center gap-1"><span className="h-3 w-0.5 bg-destructive" /> Deadline</span>}
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No tasks yet. Add tasks with start and due dates to see them here.</p>
      ) : (
        <div className="flex overflow-hidden rounded-lg border" onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={() => setDrag(null)}>
          {/* Task names */}
          <div className="w-64 shrink-0 border-r bg-card">
            <div className="flex items-end border-b px-3 pb-1.5 text-xs font-medium text-muted-foreground" style={{ height: HEADER }}>Task</div>
            {rows.map(({ task, depth }) => (
              <button key={task.id} type="button" onClick={() => setOpen(task.id)}
                className="flex w-full items-center gap-2 border-b px-3 text-left text-sm hover:bg-muted" style={{ height: ROW, paddingLeft: 12 + depth * 16 }}>
                <span className={cn("truncate", task.status === "done" && "text-muted-foreground line-through")}>{task.title}</span>
                {!task.start_date && !task.due_date && <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">no dates</span>}
              </button>
            ))}
          </div>
          {/* Chart */}
          <div className="flex-1 overflow-x-auto">
            <div className="relative" style={{ width, height: HEADER + rows.length * ROW }}>
              {months.map((m) => (
                <div key={m.label} className="absolute top-0 border-l px-1.5 pt-1 text-xs font-medium" style={{ left: x(m.from), width: (m.to - m.from + 1) * px, height: 20 }}>
                  <span className="sticky left-1 truncate">{(m.to - m.from + 1) * px > 40 ? m.label : ""}</span>
                </div>
              ))}
              {ticks.map((d) => (
                <div key={d} className="absolute border-l text-[10px] text-muted-foreground" style={{ left: x(d), top: 20, height: HEADER - 20 + rows.length * ROW }}>
                  <span className="pl-0.5">{zoom === "Month" ? "" : new Date(d * DAY).getUTCDate()}</span>
                </div>
              ))}
              {/* Weekends */}
              {zoom === "Day" && Array.from({ length: range.to - range.from + 1 }, (_, i) => range.from + i)
                .filter((d) => [0, 6].includes(new Date(d * DAY).getUTCDay()))
                .map((d) => <div key={`w${d}`} className="absolute bg-muted/50" style={{ left: x(d), top: HEADER, width: px, height: rows.length * ROW }} />)}
              <div className="absolute border-b" style={{ top: HEADER - 1, left: 0, width }} />
              {/* Row lines */}
              {rows.map((_, i) => <div key={i} className="absolute border-b" style={{ top: HEADER + (i + 1) * ROW - 1, left: 0, width }} />)}
              {/* Today and deadline */}
              <div className="absolute w-0.5 bg-primary" style={{ left: x(today) + px / 2, top: 20, height: HEADER - 20 + rows.length * ROW }} title={`Today, ${formatDate(t.today)}`} />
              {t.deadline && (
                <div className="absolute w-0.5 bg-destructive" style={{ left: x(toDay(t.deadline)) + px - 1, top: 20, height: HEADER - 20 + rows.length * ROW }} title={`Deadline, ${formatDate(t.deadline)}`} />
              )}
              {/* Milestones */}
              {t.milestones.filter((m) => m.due_date).map((m) => (
                <div key={m.id} className="absolute -translate-x-1/2" style={{ left: x(toDay(m.due_date!)) + px / 2, top: 22 }} title={`${m.name}, ${formatDate(m.due_date)}`}>
                  <Diamond className={cn("size-4", m.status === "done" ? "fill-success text-success" : "fill-warning text-warning")} />
                </div>
              ))}
              {/* Dependency arrows: from the end of the task waited for to the start of the waiting task */}
              <svg className="pointer-events-none absolute left-0 top-0" width={width} height={HEADER + rows.length * ROW} aria-hidden>
                <defs>
                  <marker id="dep-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
                    <path d="M0,0 L8,4 L0,8 z" fill="var(--muted-foreground)" />
                  </marker>
                </defs>
                {rows.flatMap(({ task }) =>
                  task.depends_on.map((dep) => {
                    const from = rows[index.get(dep) ?? -1]?.task;
                    const a = from && span(from);
                    const b = span(task);
                    if (!a || !b) return null;
                    const x1 = x(a[1]) + px;
                    const y1 = HEADER + index.get(dep)! * ROW + ROW / 2;
                    const x2 = x(b[0]);
                    const y2 = HEADER + index.get(task.id)! * ROW + ROW / 2;
                    const mid = Math.max(x1 + 8, x2 - 8);
                    return (
                      <path key={`${dep}-${task.id}`} d={`M${x1},${y1} H${mid} V${y2} H${x2}`} fill="none"
                        stroke={a[1] >= b[0] ? "var(--destructive)" : "var(--muted-foreground)"} strokeWidth={1.25} markerEnd="url(#dep-arrow)" />
                    );
                  }),
                )}
              </svg>
              {/* Bars */}
              {rows.map(({ task }, i) => {
                const s = span(task);
                if (!s) return null;
                const left = x(s[0]);
                const w = (s[1] - s[0] + 1) * px;
                const progress = Number(task.progress);
                return (
                  <div
                    key={task.id}
                    className={cn(
                      "group absolute flex items-center overflow-hidden rounded-md border text-[11px] shadow-sm",
                      task.status === "done" ? "border-success/50 bg-success/20" : "border-primary/40 bg-primary/20",
                      task.delayed && "border-2 border-destructive",
                      t.can_edit ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
                    )}
                    style={{ left, width: Math.max(w, 6), top: HEADER + i * ROW + 6, height: ROW - 12 }}
                    title={`${task.number} ${task.title}\n${formatDate(fromDay(s[0]))} – ${formatDate(fromDay(s[1]))} · ${Math.round(progress)}%${task.assignees.length ? ` · ${task.assignees.map((a) => a.name).join(", ")}` : ""}${task.delayed ? "\nDelayed" : ""}`}
                    onPointerDown={(e) => onPointerDown(e, task, "move")}
                    onClick={() => !moved.current && setOpen(task.id)}
                  >
                    <div className={cn("absolute inset-y-0 left-0", task.status === "done" ? "bg-success/60" : "bg-primary/60")} style={{ width: `${progress}%` }} />
                    {w > 60 && <span className="relative truncate px-1.5">{task.assignees.map((a) => a.name.split(" ")[0]).join(", ") || task.number}</span>}
                    {t.can_edit && (
                      <>
                        <span className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize opacity-0 group-hover:bg-foreground/30 group-hover:opacity-100" onPointerDown={(e) => onPointerDown(e, task, "start")} />
                        <span className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize opacity-0 group-hover:bg-foreground/30 group-hover:opacity-100" onPointerDown={(e) => onPointerDown(e, task, "end")} />
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
      {t.can_edit && rows.length > 0 && (
        <p className="text-xs text-muted-foreground">Drag a bar to move it; drag its edges to change the start or due date. Red arrows: a task ends after the one waiting for it starts.</p>
      )}
      {open && <TaskPanel key={open} projectId={projectId} taskId={open} onClose={() => setOpen(null)} onOpenTask={setOpen} />}
      {save.isPending && <Button variant="ghost" size="sm" loading className="self-start">Saving…</Button>}
    </div>
  );
}
