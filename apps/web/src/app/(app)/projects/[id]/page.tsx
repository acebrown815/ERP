"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Diamond, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState, TableSkeleton } from "@/components/erp/states";
import { ProjectFinancialsView } from "@/components/projects/financials";
import { Gantt } from "@/components/projects/gantt";
import { KanbanBoard } from "@/components/projects/kanban";
import { PROJECT_STATUS, ProjectDialog } from "@/components/projects/project-dialog";
import { isOverdue, PriorityLabel, ProgressBar, TASK_STATUSES, TaskStatusBadge } from "@/components/projects/shared";
import { TaskPanel } from "@/components/projects/task-panel";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/money";
import { useCan, useMe } from "@/lib/session";
import type { Milestone, Page, Project, Task, TaskProgress, Timeline } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "tasks", label: "Tasks" },
  { key: "board", label: "Board" },
  { key: "timeline", label: "Timeline" },
  { key: "financials", label: "Financials" },
] as const;

function Milestones({ project, canManage }: { project: Project; canManage: boolean }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["milestones", project.id], queryFn: () => api.get<Milestone[]>(`/projects/${project.id}/milestones`) });
  const [editing, setEditing] = useState<Partial<Milestone> | null>(null);
  const save = useMutation({
    mutationFn: (m: Partial<Milestone>) => {
      const body = { name: m.name, due_date: m.due_date || null, status: m.status ?? "planned", description: m.description ?? null };
      return m.id ? api.patch(`/milestones/${m.id}`, { ...body, version: m.version }) : api.post(`/projects/${project.id}/milestones`, body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["milestones", project.id] });
      qc.invalidateQueries({ queryKey: ["timeline", project.id] });
      setEditing(null);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not save"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/milestones/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["milestones", project.id] });
      qc.invalidateQueries({ queryKey: ["timeline", project.id] });
    },
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Milestones</CardTitle>
        {canManage && <Button size="sm" variant="outline" onClick={() => setEditing({ status: "planned" })}><Plus /> Add</Button>}
      </CardHeader>
      <CardContent>
        {!list.data?.length ? <p className="text-sm text-muted-foreground">None yet.</p> : (
          <ul className="flex flex-col gap-2 text-sm">
            {list.data.map((m) => (
              <li key={m.id} className="flex items-center gap-2">
                <Diamond className={cn("size-4", m.status === "done" ? "fill-success text-success" : "fill-warning text-warning")} />
                <span className="flex-1">{m.name}</span>
                <span className={cn("text-muted-foreground", isOverdue(m.due_date, m.status === "done" ? "done" : "open") && "text-destructive")}>{formatDate(m.due_date)}</span>
                <Badge variant={m.status === "done" ? "success" : "muted"}>{m.status.replace("_", " ")}</Badge>
                {canManage && (
                  <>
                    <Button variant="ghost" size="icon" aria-label={`Edit ${m.name}`} onClick={() => setEditing(m)}><Pencil /></Button>
                    <Button variant="ghost" size="icon" aria-label={`Delete ${m.name}`} onClick={() => remove.mutate(m.id)}><Trash2 /></Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {editing && (
        <Dialog open onOpenChange={(o) => !o && setEditing(null)}>
          <DialogContent>
            <DialogHeader><DialogTitle>{editing.id ? "Edit milestone" : "New milestone"}</DialogTitle></DialogHeader>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="ms_name" label="Name" required className="sm:col-span-2"><Input id="ms_name" value={editing.name ?? ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></FormField>
              <FormField id="ms_due" label="Due"><Input id="ms_due" type="date" value={editing.due_date ?? ""} onChange={(e) => setEditing({ ...editing, due_date: e.target.value })} /></FormField>
              <FormField id="ms_status" label="Status">
                <Select id="ms_status" value={editing.status ?? "planned"} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                  {["planned", "in_progress", "done", "cancelled"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                </Select>
              </FormField>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
              <Button disabled={!editing.name?.trim()} loading={save.isPending} onClick={() => save.mutate(editing)}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}

function Overview({ project, canManage, progress }: { project: Project; canManage: boolean; progress: TaskProgress | undefined }) {
  const isHire = useMe().restricted_access;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Details</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
            {project.customer_name && (<><dt className="text-muted-foreground">Customer</dt><dd>{project.customer_name}</dd></>)}
            <dt className="text-muted-foreground">Project manager</dt><dd>{project.manager_name ?? "—"}</dd>
            {project.hire_name && (<><dt className="text-muted-foreground">Hire</dt><dd>{project.hire_name}</dd></>)}
            <dt className="text-muted-foreground">Dates</dt><dd>{formatDate(project.start_date)} – {formatDate(project.deadline)}</dd>
            <dt className="text-muted-foreground">Priority</dt><dd><PriorityLabel priority={project.priority} /></dd>
            {!isHire && (
              <>
                <dt className="text-muted-foreground">Contract</dt><dd className="tabular">{project.contract_value ? `${formatAmount(project.contract_value)} ${project.currency}` : "—"}</dd>
                <dt className="text-muted-foreground">Budget</dt><dd className="tabular">{project.budget ? formatAmount(project.budget) : "—"}</dd>
              </>
            )}
            <dt className="text-muted-foreground">Progress</dt>
            <dd>
              <ProgressBar value={project.completion_override ?? progress?.percent ?? "0"} />
              <span className="text-xs text-muted-foreground">
                {project.completion_override ? "Set manually" : progress ? `${progress.done}/${progress.total} tasks, estimate-weighted` : "No tasks"}
              </span>
            </dd>
          </dl>
          {project.description && <p className="mt-4 whitespace-pre-wrap text-sm">{project.description}</p>}
        </CardContent>
      </Card>
      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader><CardTitle>Team</CardTitle></CardHeader>
          <CardContent>
            {project.members.length === 0 ? <p className="text-sm text-muted-foreground">No members.</p> : (
              <ul className="flex flex-col gap-1 text-sm">
                {project.members.map((m) => (
                  <li key={m.employee_id} className="flex justify-between gap-2">
                    {isHire ? <span>{m.employee_name ?? "—"}</span> : <Link href={`/employees/${m.employee_id}`} className="hover:underline">{m.employee_name ?? "—"}</Link>}
                    <span className="text-muted-foreground">{[m.role, m.default_allocation_pct ? `${m.default_allocation_pct.replace(/\.?0+$/, "")}% of revenue` : null].filter(Boolean).join(" · ")}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Milestones project={project} canManage={canManage} />
      </div>
    </div>
  );
}

function TaskList({ projectId, canCreate, onOpen }: { projectId: string; canCreate: boolean; onOpen: (id?: string) => void }) {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const tasks = useQuery({
    queryKey: ["tasks", "list", projectId, status, q],
    queryFn: async () => (await api.get<Page<Task>>("/tasks", { project_id: projectId, status: status || undefined, q, page_size: 500 })).items,
    placeholderData: keepPreviousData,
  });
  const order = Object.fromEntries(TASK_STATUSES.map((s, i) => [s.key, i]));
  const rows = [...(tasks.data ?? [])].sort((a, b) => (order[a.status] ?? 0) - (order[b.status] ?? 0) || (a.due_date ?? "9").localeCompare(b.due_date ?? "9"));
  return (
    <Card>
      <div className="flex flex-col gap-2 border-b p-3 sm:flex-row sm:items-center">
        <Input aria-label="Search tasks" placeholder="Search tasks" className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select aria-label="Status" className="sm:w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {TASK_STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </Select>
        {canCreate && <Button className="sm:ml-auto" onClick={() => onOpen()}><Plus /> New task</Button>}
      </div>
      {!tasks.data ? <TableSkeleton /> : rows.length === 0 ? <p className="p-6 text-sm text-muted-foreground">No tasks.</p> : (
        <Table>
          <THead><TR><TH>Task</TH><TH>Status</TH><TH>Assignees</TH><TH>Due</TH><TH className="text-right">Hours</TH></TR></THead>
          <TBody>
            {rows.map((t) => (
              <TR key={t.id} className="cursor-pointer" onClick={() => onOpen(t.id)}>
                <TD>
                  <span className={cn("font-medium", t.parent_task_id && "pl-4")}>{t.title}</span>
                  <span className="block font-mono text-xs text-muted-foreground">{t.number}{t.subtasks ? ` · ${t.subtasks_done}/${t.subtasks} subtasks` : ""}</span>
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
  );
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const can = useCan();
  const tab = (params.get("tab") ?? "overview") as (typeof TABS)[number]["key"];
  const [editing, setEditing] = useState(false);
  const [openTask, setOpenTask] = useState<{ id?: string } | null>(null);
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/projects/${id}`) });
  const timeline = useQuery({ queryKey: ["timeline", id], queryFn: () => api.get<Timeline>(`/projects/${id}/timeline`) });
  const progress = useQuery({ queryKey: ["task-progress", [id]], queryFn: () => api.get<TaskProgress[]>(`/tasks/progress?project_ids=${id}`) });
  if (project.isError) return <ErrorState error={project.error} onRetry={() => project.refetch()} />;
  const p = project.data;
  if (!p) return <TableSkeleton />;
  const canManageTasks = !!timeline.data?.can_edit;
  const tabs = TABS.filter((t) => t.key !== "financials" || can("projects.read_financials"));
  const go = (key: string) => router.replace(`${pathname}?tab=${key}`, { scroll: false });

  return (
    <>
      <PageHeader
        title={p.name}
        description={<><span className="font-mono">{p.number}</span> · <Badge variant={PROJECT_STATUS[p.status]?.variant}>{PROJECT_STATUS[p.status]?.label}</Badge></>}
        actions={
          <>
            <Button variant="outline" asChild><Link href="/projects"><ArrowLeft /> Projects</Link></Button>
            {p.edit_mode && <Button variant="outline" onClick={() => setEditing(true)}><Pencil /> Edit</Button>}
          </>
        }
      />
      <div className="mb-4 flex gap-1 overflow-x-auto border-b" role="tablist">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => go(t.key)}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm", tab === t.key ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview project={p} canManage={!!p.edit_mode && canManageTasks} progress={progress.data?.[0]} />}
      {tab === "tasks" && <TaskList projectId={p.id} canCreate={canManageTasks} onOpen={(taskId) => setOpenTask({ id: taskId })} />}
      {tab === "board" && <KanbanBoard projectId={p.id} />}
      {tab === "timeline" && <Card><CardContent className="pt-6"><Gantt projectId={p.id} /></CardContent></Card>}
      {tab === "financials" && <ProjectFinancialsView projectId={p.id} />}
      {editing && <ProjectDialog project={p} onClose={() => setEditing(false)} />}
      {openTask && (
        <TaskPanel key={openTask.id ?? "new"} projectId={p.id} taskId={openTask.id} onClose={() => setOpenTask(null)} onOpenTask={(tid) => setOpenTask({ id: tid })} />
      )}
    </>
  );
}
