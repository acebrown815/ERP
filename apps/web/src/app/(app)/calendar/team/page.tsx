"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CalendarView } from "@/components/calendar/calendar-view";
import { Workload } from "@/components/calendar/workload";
import { PageHeader } from "@/components/erp/page-header";
import { ProjectSelect } from "@/components/projects/shared";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useDepartments } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { CalendarEvent, Employee } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

const TABS = ["calendar", "workload", "leave"] as const;

function PendingLeave() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["leave-pending"], queryFn: () => api.get<CalendarEvent[]>("/calendar/leave/pending") });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.post(`/calendar/events/${id}/decision`, { approve }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["leave-pending"] });
      qc.invalidateQueries({ queryKey: ["calendar"] });
      qc.invalidateQueries({ queryKey: ["workload"] });
      toast.success(v.approve ? "Leave approved" : "Leave rejected");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not decide"),
  });
  return (
    <Card>
      <CardHeader><CardTitle>Leave requests waiting for you</CardTitle></CardHeader>
      <CardContent>
        {!q.data?.length ? <p className="text-sm text-muted-foreground">Nothing to approve.</p> : (
          <ul className="divide-y text-sm">
            {q.data.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-3 py-2">
                <span className="font-medium">{e.owner_name}</span>
                <span>{e.title}</span>
                <span className="text-muted-foreground">{formatDate(e.start_date)} – {formatDate(e.end_date)}</span>
                {e.description && <span className="text-xs text-muted-foreground">“{e.description}”</span>}
                <span className="ml-auto flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: e.id, approve: false })}><X /> Reject</Button>
                  <Button size="sm" onClick={() => decide.mutate({ id: e.id, approve: true })}><Check /> Approve</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function TeamCalendarPage() {
  const can = useCan();
  const departments = useDepartments();
  const me = useQuery({ queryKey: ["employee", "me"], queryFn: () => api.get<Employee>("/employees/me"), retry: false });
  const [by, setBy] = useState<"department" | "project">("department");
  const [departmentId, setDepartmentId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("calendar");
  useEffect(() => {
    if (!departmentId && me.data?.department_id) setDepartmentId(me.data.department_id);
  }, [me.data, departmentId]);
  const dept = by === "department" ? departmentId : null;
  const proj = by === "project" ? projectId : null;
  const ready = !!dept || !!proj;
  return (
    <>
      <PageHeader
        title="Team calendar"
        description="Your team's meetings, leave and tasks, and who has room this fortnight."
        actions={
          <>
            <Select aria-label="Team by" className="w-36" value={by} onChange={(e) => setBy(e.target.value as typeof by)}>
              <option value="department">Department</option>
              <option value="project">Project team</option>
            </Select>
            {by === "department" ? (
              <Select aria-label="Department" className="w-48" value={departmentId ?? ""} onChange={(e) => setDepartmentId(e.target.value || null)}>
                <option value="" disabled>Choose…</option>
                {departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            ) : (
              <ProjectSelect value={projectId} onChange={setProjectId} />
            )}
          </>
        }
      />
      <div className="mb-4 flex gap-1 border-b" role="tablist">
        {TABS.filter((t) => t !== "leave" || can("leave.approve")).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm capitalize", tab === t ? "border-primary font-medium" : "border-transparent text-muted-foreground")}>
            {t === "leave" ? "Leave requests" : t}
          </button>
        ))}
      </div>
      {!ready && tab !== "leave" ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          {by === "department" ? "Choose a department" : "Choose a project"} to see its calendar.
          {by === "department" && me.data && !me.data.department_id && <Badge variant="muted" className="ml-2">You&apos;re not in a department</Badge>}
        </CardContent></Card>
      ) : tab === "calendar" ? (
        <Card><CardContent className="pt-6"><CalendarView view="team" departmentId={dept} projectId={proj} defaults={proj ? { scope: "project", projectId: proj } : { scope: "team", departmentId: dept }} /></CardContent></Card>
      ) : tab === "workload" ? (
        <Card><CardContent className="pt-6"><Workload departmentId={dept} projectId={proj} /></CardContent></Card>
      ) : (
        <PendingLeave />
      )}
    </>
  );
}
