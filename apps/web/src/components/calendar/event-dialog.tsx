"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { CategorySelect, useCategories, type CategoryValue } from "@/components/erp/category-select";
import { FormField } from "@/components/erp/form-field";
import { ProjectPicker } from "@/components/erp/pickers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox, Input, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useDepartments, useEmployees } from "@/lib/queries";
import { useCan } from "@/lib/session";
import type { CalendarEvent, Employee } from "@/lib/types";

import { browserTimeZone, describeRRule, fmtDay, fromRRule, iso, toRRule, type Repeat } from "./utils";

const errorText = (err: unknown) =>
  err instanceof ApiError ? [err.message, ...err.errors.map((e) => e.message)].filter((v, i, a) => a.indexOf(v) === i).join(" · ") : "Something went wrong";

const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const REMINDERS = [
  { v: 0, label: "At start" },
  { v: 5, label: "5 min before" },
  { v: 15, label: "15 min before" },
  { v: 30, label: "30 min before" },
  { v: 60, label: "1 hour before" },
  { v: 1440, label: "1 day before" },
];

/** "YYYY-MM-DDTHH:mm" in the viewer's zone for an instant. */
function localInput(instant: string | null | undefined): string {
  if (!instant) return "";
  const d = new Date(instant);
  return `${iso(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

type Form = {
  title: string;
  type: CategoryValue;
  scope: "personal" | "team" | "project" | "company";
  department_id: string | null;
  project_id: string | null;
  all_day: boolean;
  start_date: string;
  end_date: string;
  start_at: string;
  end_at: string;
  repeat: Repeat;
  reminders: number[];
  attendee_ids: string[];
  location: string;
  description: string;
};

export type EventDefaults = { date?: string; scope?: Form["scope"]; projectId?: string | null; departmentId?: string | null; leave?: boolean };

function blank(d: EventDefaults, leaveTypeId: string | null): Form {
  const day = d.date ?? iso(new Date());
  return {
    title: d.leave ? "Leave" : "",
    type: { category_id: d.leave ? leaveTypeId : null, other_text: "" },
    scope: d.scope ?? "personal",
    department_id: d.departmentId ?? null,
    project_id: d.projectId ?? null,
    all_day: !!d.leave,
    start_date: day,
    end_date: day,
    start_at: `${day}T09:00`,
    end_at: `${day}T10:00`,
    repeat: { freq: "", byday: [], end: "never", until: "", count: "" },
    reminders: d.leave ? [] : [15],
    attendee_ids: [],
    location: "",
    description: "",
  };
}

function fromEvent(e: CalendarEvent): Form {
  return {
    title: e.title,
    type: { category_id: e.event_type_category_id ?? null, other_text: e.event_type_other_text ?? "" },
    scope: e.scope as Form["scope"],
    department_id: e.department_id ?? null,
    project_id: e.project_id ?? null,
    all_day: e.all_day,
    start_date: e.start_date ?? iso(new Date()),
    end_date: e.end_date ?? e.start_date ?? iso(new Date()),
    start_at: localInput(e.start_at),
    end_at: localInput(e.end_at),
    repeat: fromRRule(e.rrule),
    reminders: e.reminders,
    attendee_ids: e.attendees.map((a) => a.employee_id),
    location: e.location ?? "",
    description: e.description ?? "",
  };
}

function Attendees({ value, onChange, employees }: { value: string[]; onChange: (v: string[]) => void; employees: Employee[] }) {
  const [q, setQ] = useState("");
  const list = employees.filter((e) => e.status !== "terminated" && (value.includes(e.id) || e.full_name.toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="flex flex-col gap-2">
      <Input aria-label="Find people" placeholder="Find people…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="flex max-h-32 flex-wrap gap-x-4 gap-y-1.5 overflow-y-auto">
        {list.slice(0, 40).map((e) => (
          <label key={e.id} className="flex items-center gap-2 text-sm">
            <Checkbox checked={value.includes(e.id)} onChange={(ev) => onChange(ev.target.checked ? [...value, e.id] : value.filter((x) => x !== e.id))} />
            {e.full_name}
          </label>
        ))}
      </div>
    </div>
  );
}

/** Create or edit an event (meeting, leave, company event…), including repeats, reminders and attendees. */
export function EventDialog({ eventId, occurrence, defaults = {}, onClose }: { eventId?: string; occurrence?: string | null; defaults?: EventDefaults; onClose: () => void }) {
  const qc = useQueryClient();
  const can = useCan();
  const employees = useEmployees();
  const departments = useDepartments();
  const types = useCategories("event_type");
  const leaveTypeId = types.data?.find((t) => t.system_key === "leave")?.id ?? null;
  const me = useQuery({ queryKey: ["employee", "me"], queryFn: () => api.get<Employee>("/employees/me"), retry: false });
  const event = useQuery({ queryKey: ["calendar-event", eventId], queryFn: () => api.get<CalendarEvent>(`/calendar/events/${eventId}`), enabled: !!eventId });
  const [form, setForm] = useState<Form | null>(null);
  const e = event.data;
  const current = form ?? (e ? fromEvent(e) : eventId ? null : types.data ? blank(defaults, leaveTypeId) : null);
  const set = (patch: Partial<Form>) => setForm({ ...(current as Form), ...patch });
  const isLeave = useMemo(
    () => !!types.data?.find((t) => t.id === current?.type.category_id)?.config?.counts_as_unavailable,
    [types.data, current?.type.category_id],
  );
  const readOnly = !!e && !e.editable;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["calendar"] });
    qc.invalidateQueries({ queryKey: ["calendar-event"] });
    qc.invalidateQueries({ queryKey: ["leave-pending"] });
    qc.invalidateQueries({ queryKey: ["workload"] });
  };

  const save = useMutation({
    mutationFn: () => {
      const f = current!;
      const body = {
        title: f.title,
        scope: f.scope,
        event_type_category_id: f.type.category_id,
        event_type_other_text: f.type.other_text || null,
        department_id: f.scope === "team" ? f.department_id ?? me.data?.department_id ?? null : null,
        project_id: f.scope === "project" ? f.project_id : null,
        all_day: f.all_day,
        start_date: f.all_day ? f.start_date : null,
        end_date: f.all_day ? f.end_date : null,
        start_at: f.all_day ? null : new Date(f.start_at).toISOString(),
        end_at: f.all_day ? null : new Date(f.end_at).toISOString(),
        timezone: e?.timezone ?? browserTimeZone(),
        rrule: toRRule(f.repeat),
        reminders: f.reminders,
        attendee_ids: f.attendee_ids,
        location: f.location || null,
        description: f.description || null,
      };
      return e ? api.patch<CalendarEvent>(`/calendar/events/${e.id}`, { ...body, version: e.version }) : api.post<CalendarEvent>("/calendar/events", body);
    },
    onSuccess: (saved) => {
      refresh();
      toast.success(saved.status === "requested" ? "Leave requested; your manager will review it" : e ? "Event saved" : "Event added");
      onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const act = useMutation({
    mutationFn: (action: "delete" | "skip" | "approve" | "reject" | "accepted" | "declined") => {
      if (action === "delete") return api.delete(`/calendar/events/${e!.id}`);
      if (action === "skip") return api.post(`/calendar/events/${e!.id}/cancel-occurrence`, { occurrence });
      if (action === "approve" || action === "reject") return api.post(`/calendar/events/${e!.id}/decision`, { approve: action === "approve" });
      return api.post(`/calendar/events/${e!.id}/respond`, { response: action });
    },
    onSuccess: (_d, action) => {
      refresh();
      toast.success({ delete: "Deleted", skip: "This occurrence is skipped", approve: "Leave approved", reject: "Leave rejected", accepted: "Accepted", declined: "Declined" }[action]);
      if (action !== "accepted" && action !== "declined") onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });

  const myAttendance = e?.attendees.find((a) => a.employee_id === me.data?.id);
  const scopes = [
    { key: "personal", label: "My calendar", show: !!me.data || can("calendar.manage.company") },
    { key: "team", label: "Team (department)", show: can("calendar.manage.team") },
    { key: "project", label: "Project", show: can("tasks.manage") },
    { key: "company", label: "Company", show: can("calendar.manage.company") },
  ].filter((s) => s.show || s.key === current?.scope);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {e ? e.title : defaults.leave ? "Request leave" : "New event"}
            {e && e.status !== "confirmed" && <Badge variant={e.status === "approved" ? "success" : e.status === "rejected" ? "destructive" : "warning"}>{e.status}</Badge>}
          </DialogTitle>
          {e && (
            <DialogDescription>
              {e.owner_name ? `${e.owner_name} · ` : ""}{describeRRule(e.rrule)}{occurrence ? ` · this occurrence: ${occurrence.slice(0, 16).replace("T", " ")}` : ""}
            </DialogDescription>
          )}
        </DialogHeader>
        {!current ? <p className="text-sm text-muted-foreground">Loading…</p> : (
          <fieldset disabled={readOnly} className="grid gap-4 sm:grid-cols-2">
            <FormField id="ev_title" label="Title" required className="sm:col-span-2">
              <Input id="ev_title" value={current.title} onChange={(ev) => set({ title: ev.target.value })} autoFocus={!e} />
            </FormField>
            <CategorySelect group="event_type" label="Type" value={current.type} onChange={(v) => set({ type: v, ...(types.data?.find((t) => t.id === v.category_id)?.config?.counts_as_unavailable ? { all_day: true, scope: "personal" } : {}) })} />
            <FormField id="ev_scope" label="Calendar">
              <Select id="ev_scope" value={current.scope} disabled={isLeave} onChange={(ev) => set({ scope: ev.target.value as Form["scope"] })}>
                {scopes.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </Select>
            </FormField>
            {current.scope === "team" && (
              <FormField id="ev_dept" label="Team">
                <Select id="ev_dept" value={current.department_id ?? me.data?.department_id ?? ""} onChange={(ev) => set({ department_id: ev.target.value || null })}>
                  <option value="">Choose…</option>
                  {departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </Select>
              </FormField>
            )}
            {current.scope === "project" && (
              <FormField id="ev_project" label="Project"><ProjectPicker id="ev_project" value={current.project_id} onChange={(v) => set({ project_id: v })} /></FormField>
            )}
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <Checkbox checked={current.all_day} disabled={isLeave} onChange={(ev) => set({ all_day: ev.target.checked })} /> All day
            </label>
            {current.all_day ? (
              <>
                <FormField id="ev_sd" label="From"><Input id="ev_sd" type="date" value={current.start_date} onChange={(ev) => set({ start_date: ev.target.value, end_date: current.end_date < ev.target.value ? ev.target.value : current.end_date })} /></FormField>
                <FormField id="ev_ed" label="To (inclusive)"><Input id="ev_ed" type="date" value={current.end_date} onChange={(ev) => set({ end_date: ev.target.value })} /></FormField>
              </>
            ) : (
              <>
                <FormField id="ev_sa" label="Starts"><Input id="ev_sa" type="datetime-local" value={current.start_at} onChange={(ev) => set({ start_at: ev.target.value })} /></FormField>
                <FormField id="ev_ea" label="Ends" hint={`Times in ${e?.timezone ?? browserTimeZone()}`}><Input id="ev_ea" type="datetime-local" value={current.end_at} onChange={(ev) => set({ end_at: ev.target.value })} /></FormField>
              </>
            )}
            {!isLeave && (
              <>
                <FormField id="ev_repeat" label="Repeats">
                  <Select id="ev_repeat" value={current.repeat.freq} onChange={(ev) => set({ repeat: { ...current.repeat, freq: ev.target.value as Repeat["freq"] } })}>
                    <option value="">Does not repeat</option>
                    <option value="DAILY">Daily</option>
                    <option value="WEEKLY">Weekly</option>
                    <option value="MONTHLY">Monthly</option>
                    <option value="YEARLY">Yearly</option>
                  </Select>
                </FormField>
                {current.repeat.freq ? (
                  <FormField id="ev_end" label="Ends">
                    <div className="flex gap-2">
                      <Select id="ev_end" className="w-28" value={current.repeat.end} onChange={(ev) => set({ repeat: { ...current.repeat, end: ev.target.value as Repeat["end"] } })}>
                        <option value="never">Never</option>
                        <option value="until">On</option>
                        <option value="count">After</option>
                      </Select>
                      {current.repeat.end === "until" && <Input aria-label="Last date" type="date" value={current.repeat.until} onChange={(ev) => set({ repeat: { ...current.repeat, until: ev.target.value } })} />}
                      {current.repeat.end === "count" && <Input aria-label="Times" inputMode="numeric" placeholder="times" value={current.repeat.count} onChange={(ev) => set({ repeat: { ...current.repeat, count: ev.target.value } })} />}
                    </div>
                  </FormField>
                ) : <div />}
                {current.repeat.freq === "WEEKLY" && (
                  <div className="flex flex-wrap gap-1 sm:col-span-2" role="group" aria-label="On days">
                    {WEEKDAYS.map((d) => (
                      <button key={d} type="button" aria-pressed={current.repeat.byday.includes(d)}
                        onClick={() => set({ repeat: { ...current.repeat, byday: current.repeat.byday.includes(d) ? current.repeat.byday.filter((x) => x !== d) : [...current.repeat.byday, d] } })}
                        className={`rounded border px-2 py-1 text-xs ${current.repeat.byday.includes(d) ? "border-primary bg-accent font-medium" : "text-muted-foreground"}`}>
                        {d}
                      </button>
                    ))}
                  </div>
                )}
                <FormField id="ev_rem" label="Reminders" className="sm:col-span-2">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {REMINDERS.map((r) => (
                      <label key={r.v} className="flex items-center gap-2 text-sm">
                        <Checkbox checked={current.reminders.includes(r.v)} onChange={(ev) => set({ reminders: ev.target.checked ? [...current.reminders, r.v] : current.reminders.filter((x) => x !== r.v) })} />
                        {r.label}
                      </label>
                    ))}
                  </div>
                </FormField>
                <FormField id="ev_people" label="Attendees" className="sm:col-span-2">
                  <Attendees value={current.attendee_ids} onChange={(v) => set({ attendee_ids: v })} employees={employees.data ?? []} />
                </FormField>
                <FormField id="ev_loc" label="Location / link" className="sm:col-span-2"><Input id="ev_loc" value={current.location} onChange={(ev) => set({ location: ev.target.value })} /></FormField>
              </>
            )}
            <FormField id="ev_desc" label={isLeave ? "Note for your manager" : "Description"} className="sm:col-span-2">
              <Textarea id="ev_desc" rows={2} value={current.description} onChange={(ev) => set({ description: ev.target.value })} />
            </FormField>
          </fieldset>
        )}
        {e && e.attendees.length > 0 && (
          <p className="text-xs text-muted-foreground">
            {e.attendees.map((a) => `${a.name} (${a.response.replace("_", " ")})`).join(", ")}
          </p>
        )}
        <DialogFooter className="flex-wrap gap-2">
          {e?.editable && <Button variant="ghost" className="mr-auto text-destructive" loading={act.isPending} onClick={() => act.mutate("delete")}><Trash2 /> Delete{e.rrule ? " series" : ""}</Button>}
          {e?.editable && e.rrule && occurrence && <Button variant="outline" onClick={() => act.mutate("skip")}>Skip this one ({fmtDay(occurrence.slice(0, 10))})</Button>}
          {myAttendance && !e?.editable && (
            <>
              <Button variant="outline" onClick={() => act.mutate("declined")}><X /> Decline</Button>
              <Button variant="outline" onClick={() => act.mutate("accepted")}><Check /> Accept</Button>
            </>
          )}
          {e?.status === "requested" && can("leave.approve") && (
            <>
              <Button variant="outline" onClick={() => act.mutate("reject")}><X /> Reject</Button>
              <Button onClick={() => act.mutate("approve")}><Check /> Approve</Button>
            </>
          )}
          {!readOnly && current && (
            <Button disabled={!current.title.trim()} loading={save.isPending} onClick={() => save.mutate()}>
              {e ? "Save" : isLeave ? "Request leave" : "Add event"}
            </Button>
          )}
          {readOnly && <Button variant="outline" onClick={onClose}>Close</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
