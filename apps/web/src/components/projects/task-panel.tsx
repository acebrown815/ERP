"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CornerDownRight, Link2, MessageSquare, Plus, Timer, Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { useEmployees } from "@/lib/queries";
import type { Milestone, Page, Project, Task, TaskComment, TaskDetail, TimeEntry } from "@/lib/types";
import { cn, formatDate, formatDateTime } from "@/lib/utils";
import { useMe } from "@/lib/session";

import { isOverdue, ProjectSelect, TASK_STATUSES, TaskStatusBadge } from "./shared";

const errorText = (err: unknown) =>
  err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].filter((v, i, a) => a.indexOf(v) === i).join(" · ") : "Something went wrong";

type Form = {
  title: string;
  description: string;
  status: string;
  priority: string;
  start_date: string;
  due_date: string;
  estimate_hours: string;
  milestone_id: string;
  assignee_ids: string[];
};

const trim = (v: string | null | undefined) => (v ? v.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") : "");

function toForm(t?: TaskDetail, defaults?: Partial<Form>): Form {
  return {
    title: t?.title ?? "",
    description: t?.description ?? "",
    status: t?.status ?? defaults?.status ?? "todo",
    priority: t?.priority ?? "medium",
    start_date: t?.start_date ?? "",
    due_date: t?.due_date ?? "",
    estimate_hours: trim(t?.estimate_hours),
    milestone_id: t?.milestone_id ?? "",
    assignee_ids: t?.assignees.map((a) => a.id) ?? defaults?.assignee_ids ?? [],
  };
}

function body(f: Form) {
  return {
    title: f.title,
    description: f.description || null,
    status: f.status,
    priority: f.priority,
    start_date: f.start_date || null,
    due_date: f.due_date || null,
    estimate_hours: f.estimate_hours || null,
    milestone_id: f.milestone_id || null,
    assignee_ids: f.assignee_ids,
  };
}

function TaskFields({ form, set, editable, statusEditable, project, milestones }: {
  form: Form;
  set: (patch: Partial<Form>) => void;
  editable: boolean;
  statusEditable: boolean;
  project: Project | undefined;
  milestones: Milestone[];
}) {
  // Names come with the project: employees and hires can't list the directory, but do work with their team.
  const employees = useEmployees(!useMe().restricted_access);
  const team = new Map<string, string>();
  for (const m of project?.members ?? []) team.set(m.employee_id, m.employee_name ?? "?");
  if (project?.manager_employee_id) team.set(project.manager_employee_id, project.manager_name ?? "?");
  if (project?.hire_employee_id) team.set(project.hire_employee_id, project.hire_name ?? "?");
  for (const e of employees.data ?? []) if (form.assignee_ids.includes(e.id)) team.set(e.id, e.full_name);
  const people = [...team].map(([id, full_name]) => ({ id, full_name })).sort((a, b) => a.full_name.localeCompare(b.full_name));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <fieldset disabled={!editable} className="contents">
        <FormField id="t_title" label="Title" required className="sm:col-span-2">
          <Input id="t_title" value={form.title} onChange={(e) => set({ title: e.target.value })} autoFocus={editable} />
        </FormField>
      </fieldset>
      <FormField id="t_status" label="Status">
        <Select id="t_status" value={form.status} disabled={!statusEditable} onChange={(e) => set({ status: e.target.value })}>
          {TASK_STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </Select>
      </FormField>
      <fieldset disabled={!editable} className="contents">
      <FormField id="t_priority" label="Priority">
        <Select id="t_priority" value={form.priority} onChange={(e) => set({ priority: e.target.value })}>
          {["low", "medium", "high", "urgent"].map((p) => <option key={p} value={p}>{p[0]!.toUpperCase() + p.slice(1)}</option>)}
        </Select>
      </FormField>
      <FormField id="t_start" label="Start"><Input id="t_start" type="date" value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} /></FormField>
      <FormField id="t_due" label="Due"><Input id="t_due" type="date" value={form.due_date} onChange={(e) => set({ due_date: e.target.value })} /></FormField>
      <FormField id="t_est" label="Estimate (hours)"><Input id="t_est" inputMode="decimal" className="tabular" value={form.estimate_hours} onChange={(e) => set({ estimate_hours: e.target.value.trim() })} /></FormField>
      <FormField id="t_ms" label="Milestone">
        <Select id="t_ms" value={form.milestone_id} onChange={(e) => set({ milestone_id: e.target.value })}>
          <option value="">None</option>
          {milestones.map((m) => <option key={m.id} value={m.id}>{m.name}{m.due_date ? ` · ${formatDate(m.due_date)}` : ""}</option>)}
        </Select>
      </FormField>
      <FormField id="t_assignees" label="Assignees" className="sm:col-span-2" hint={people.length ? undefined : "Add people to the project team first."}>
        <div id="t_assignees" className="flex flex-wrap gap-x-4 gap-y-2">
          {people.map((e) => (
            <label key={e.id} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.assignee_ids.includes(e.id)}
                onChange={(ev) => set({ assignee_ids: ev.target.checked ? [...form.assignee_ids, e.id] : form.assignee_ids.filter((x) => x !== e.id) })}
              />
              {e.full_name}
            </label>
          ))}
        </div>
      </FormField>
      <FormField id="t_desc" label="Description" className="sm:col-span-2">
        <Textarea id="t_desc" rows={4} value={form.description} onChange={(e) => set({ description: e.target.value })} />
      </FormField>
      </fieldset>
    </div>
  );
}

function Section({ icon: Icon, title, children, action }: { icon: typeof Timer; title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t pt-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-medium"><Icon className="size-4 text-muted-foreground" /> {title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/**
 * Create a task (no taskId) or open one: details, subtasks, dependencies, time and comments.
 * Managers edit everything; assignees can change the status and log their time; everyone on the project comments.
 */
export function TaskPanel({
  projectId: givenProjectId,
  taskId,
  parentTaskId,
  defaultStatus,
  onClose,
  onOpenTask,
}: {
  /** Omit when creating from a cross-project page: the form then asks for the project. */
  projectId?: string;
  taskId?: string;
  parentTaskId?: string;
  defaultStatus?: string;
  onClose: () => void;
  onOpenTask?: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [chosenProject, setChosenProject] = useState<string | null>(null);
  const projectId = givenProjectId ?? chosenProject ?? "";
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.get<Project>(`/projects/${projectId}`), enabled: !!projectId });
  const milestones = useQuery({
    queryKey: ["milestones", projectId],
    queryFn: () => api.get<Milestone[]>(`/projects/${projectId}/milestones`),
    enabled: !!projectId,
  });
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api.get<TaskDetail>(`/tasks/${taskId}`), enabled: !!taskId });
  const [form, setForm] = useState<Form | null>(taskId ? null : toForm(undefined, { status: defaultStatus }));
  const [deleting, setDeleting] = useState(false);
  const t = task.data;
  const current = form ?? (t ? toForm(t) : null);
  const set = (patch: Partial<Form>) => setForm({ ...(current as Form), ...patch });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["tasks"] });
    qc.invalidateQueries({ queryKey: ["task"] });
    qc.invalidateQueries({ queryKey: ["timeline", projectId] });
    qc.invalidateQueries({ queryKey: ["task-progress"] });
  };

  const save = useMutation({
    mutationFn: () => {
      if (!t) return api.post<TaskDetail>("/tasks", { project_id: projectId, parent_task_id: parentTaskId ?? null, ...body(current!) });
      if (t.can_edit) return api.patch<TaskDetail>(`/tasks/${t.id}`, { version: t.version, ...body(current!) });
      return api.patch<TaskDetail>(`/tasks/${t.id}`, { version: t.version, status: current!.status });
    },
    onSuccess: (saved) => {
      refresh();
      toast.success(t ? "Task saved" : `${saved.number} created`);
      if (t) setForm(null);
      else onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });

  const readOnly = !!t && !t.can_edit;
  const dirty = !!form;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {t ? (
              <>
                <span className="font-mono text-sm text-muted-foreground">{t.number}</span> {t.title}
                <TaskStatusBadge status={t.status} />
                {isOverdue(t.due_date, t.status) && <Badge variant="destructive">Overdue</Badge>}
              </>
            ) : parentTaskId ? "New subtask" : "New task"}
          </DialogTitle>
        </DialogHeader>
        {t?.parent && (
          <button type="button" className="flex w-fit items-center gap-1 text-sm text-primary hover:underline" onClick={() => onOpenTask?.(t.parent!.id)}>
            <CornerDownRight className="size-4" /> Subtask of {t.parent.number} {t.parent.title}
          </button>
        )}
        {!givenProjectId && !t && (
          <FormField id="t_project" label="Project" required hint="Tasks can be added to projects you manage.">
            <ProjectSelect value={chosenProject} onChange={setChosenProject} />
          </FormField>
        )}
        {!current ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <>
            <TaskFields form={current} set={set} editable={!readOnly} statusEditable={!readOnly || !!t?.can_move} project={project.data} milestones={milestones.data ?? []} />
            {readOnly && t?.can_move && <p className="text-xs text-muted-foreground">You&apos;re assigned: you can change the status and log time. Other details are set by the project&apos;s managers.</p>}
            {(!t || dirty) && (
              <DialogFooter>
                {t && <Button variant="outline" onClick={() => setForm(null)}>Discard changes</Button>}
                <Button disabled={!current.title.trim() || !projectId} loading={save.isPending} onClick={() => save.mutate()}>{t ? "Save" : "Create task"}</Button>
              </DialogFooter>
            )}
          </>
        )}
        {t && (
          <div className="flex flex-col gap-4">
            <Subtasks task={t} projectId={projectId} onOpenTask={onOpenTask} />
            <Dependencies task={t} projectId={projectId} onOpenTask={onOpenTask} onChanged={refresh} />
            <TimeLog task={t} onChanged={refresh} />
            <Comments task={t} />
            {t.can_edit && (
              <div className="flex justify-end border-t pt-4">
                <Button variant="ghost" className="text-destructive" onClick={() => setDeleting(true)}><Trash2 /> Delete task</Button>
              </div>
            )}
          </div>
        )}
        {deleting && t && (
          <ConfirmDialog
            open
            onOpenChange={setDeleting}
            destructive
            title={`Delete ${t.number}?`}
            description="Its subtasks, comments and dependencies are deleted too. Tasks with logged time can't be deleted."
            confirmLabel="Delete"
            onConfirm={async () => {
              await api.delete(`/tasks/${t.id}`);
              refresh();
              onClose();
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function Subtasks({ task, projectId, onOpenTask }: { task: TaskDetail; projectId: string; onOpenTask?: (id: string) => void }) {
  const [adding, setAdding] = useState(false);
  return (
    <Section
      icon={CornerDownRight}
      title={`Subtasks${task.children.length ? ` (${task.children.filter((c) => c.status === "done").length}/${task.children.length})` : ""}`}
      action={task.can_edit && <Button variant="ghost" size="sm" onClick={() => setAdding(true)}><Plus /> Add</Button>}
    >
      {task.children.length === 0 ? <p className="text-sm text-muted-foreground">None.</p> : (
        <ul className="flex flex-col gap-1 text-sm">
          {task.children.map((c) => (
            <li key={c.id}>
              <button type="button" className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-muted" onClick={() => onOpenTask?.(c.id)}>
                <TaskStatusBadge status={c.status} />
                <span className={cn("flex-1 truncate", c.status === "done" && "text-muted-foreground line-through")}>{c.title}</span>
                <span className="text-xs text-muted-foreground">{c.assignees.map((a) => a.name).join(", ")}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {adding && <TaskPanel projectId={projectId} parentTaskId={task.id} onClose={() => setAdding(false)} />}
    </Section>
  );
}

function Dependencies({ task, projectId, onOpenTask, onChanged }: { task: TaskDetail; projectId: string; onOpenTask?: (id: string) => void; onChanged: () => void }) {
  const qc = useQueryClient();
  const [pick, setPick] = useState("");
  const others = useQuery({
    queryKey: ["tasks", "all", projectId],
    queryFn: async () => (await api.get<Page<Task>>("/tasks", { project_id: projectId, page_size: 500 })).items,
    enabled: task.can_edit,
  });
  const change = useMutation({
    mutationFn: (args: { add?: string; remove?: string }) =>
      args.add
        ? api.post<TaskDetail>(`/tasks/${task.id}/dependencies`, { depends_on_task_id: args.add })
        : api.delete<TaskDetail>(`/tasks/${task.id}/dependencies/${args.remove}`),
    onSuccess: (d) => {
      qc.setQueryData(["task", task.id], d);
      setPick("");
      onChanged();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const candidates = (others.data ?? []).filter((o) => o.id !== task.id && !task.depends_on.includes(o.id));
  return (
    <Section icon={Link2} title="Dependencies">
      <p className="text-xs text-muted-foreground">This task can start when these are done.</p>
      {task.dependencies.length === 0 && <p className="text-sm text-muted-foreground">None.</p>}
      <ul className="flex flex-col gap-1 text-sm">
        {task.dependencies.map((d) => (
          <li key={d.id} className="flex items-center gap-2">
            <TaskStatusBadge status={d.status} />
            <button type="button" className="flex-1 truncate text-left hover:underline" onClick={() => onOpenTask?.(d.id)}>{d.number} {d.title}</button>
            {task.can_edit && <Button variant="ghost" size="icon" aria-label={`Remove dependency on ${d.number}`} onClick={() => change.mutate({ remove: d.id })}><X /></Button>}
          </li>
        ))}
      </ul>
      {task.can_edit && (
        <div className="flex gap-2">
          <Select aria-label="Add dependency" value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Waits for…</option>
            {candidates.map((o) => <option key={o.id} value={o.id}>{o.number} {o.title}</option>)}
          </Select>
          <Button variant="outline" disabled={!pick} loading={change.isPending} onClick={() => change.mutate({ add: pick })}>Add</Button>
        </div>
      )}
      {task.blocking.length > 0 && (
        <p className="text-xs text-muted-foreground">Waiting for this task: {task.blocking.map((b) => `${b.number} ${b.title}`).join(", ")}</p>
      )}
    </Section>
  );
}

function TimeLog({ task, onChanged }: { task: TaskDetail; onChanged: () => void }) {
  const qc = useQueryClient();
  const entries = useQuery({ queryKey: ["time", task.id], queryFn: () => api.get<TimeEntry[]>(`/tasks/${task.id}/time-entries`) });
  const [form, setForm] = useState({ work_date: new Date().toISOString().slice(0, 10), hours: "", note: "" });
  const log = useMutation({
    mutationFn: () => api.post(`/tasks/${task.id}/time-entries`, { ...form, note: form.note || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["time", task.id] });
      setForm({ ...form, hours: "", note: "" });
      onChanged();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/time-entries/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["time", task.id] });
      onChanged();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Section icon={Timer} title={`Time · ${formatAmount(task.logged_hours, 1)} h${task.estimate_hours ? ` of ${formatAmount(task.estimate_hours, 1)} h` : ""}`}>
      {(entries.data ?? []).length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {entries.data!.map((e) => (
            <li key={e.id} className="flex items-center gap-2">
              <span className="w-24 text-muted-foreground">{formatDate(e.work_date)}</span>
              <span className="w-28 truncate">{e.employee_name}</span>
              <span className="tabular w-12 text-right">{formatAmount(e.hours, 2).replace(/\.00$/, "")} h</span>
              <span className="flex-1 truncate text-muted-foreground">{e.note}</span>
              <Button variant="ghost" size="icon" aria-label="Delete time entry" onClick={() => remove.mutate(e.id)}><X /></Button>
            </li>
          ))}
        </ul>
      )}
      {task.can_move && (
        <div className="grid grid-cols-[9rem_5rem_1fr_auto] gap-2">
          <Input aria-label="Date" type="date" value={form.work_date} onChange={(e) => setForm({ ...form, work_date: e.target.value })} />
          <Input aria-label="Hours" inputMode="decimal" placeholder="h" className="tabular" value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value.trim() })} />
          <Input aria-label="Note" placeholder="What did you do?" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          <Button variant="outline" disabled={!form.hours} loading={log.isPending} onClick={() => log.mutate()}>Log</Button>
        </div>
      )}
    </Section>
  );
}

function Comments({ task }: { task: TaskDetail }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["comments", task.id], queryFn: () => api.get<TaskComment[]>(`/tasks/${task.id}/comments`) });
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/tasks/${task.id}/comments`, { body: text }),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["comments", task.id] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Section icon={MessageSquare} title="Comments">
      <ul className="flex flex-col gap-3 text-sm">
        {(list.data ?? []).map((c) => (
          <li key={c.id}>
            <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">{c.author_name}</span> · {formatDateTime(c.created_at)}</p>
            <p className="whitespace-pre-wrap">{c.body}</p>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Textarea aria-label="Comment" rows={2} placeholder="Write a comment…" value={text} onChange={(e) => setText(e.target.value)} />
        <Button variant="outline" className="self-end" disabled={!text.trim()} loading={add.isPending} onClick={() => add.mutate()}>Post</Button>
      </div>
    </Section>
  );
}

