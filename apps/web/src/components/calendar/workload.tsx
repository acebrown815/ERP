"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { WorkloadRow } from "@/lib/types";
import { cn } from "@/lib/utils";

import { addDays, fmtDay, iso, weekStart } from "./utils";

/** Load ÷ capacity per day as a heat strip (display only, floats are fine). */
function cellClass(load: number, capacity: number, onLeave: boolean): string {
  if (onLeave) return "bg-amber-500/25 text-amber-800 dark:text-amber-200";
  if (capacity === 0) return load > 0 ? "bg-red-500/30" : "bg-muted/60 text-muted-foreground";
  const r = load / capacity;
  if (r > 1.1) return "bg-red-500/40 text-red-900 dark:text-red-100";
  if (r > 0.85) return "bg-orange-400/35";
  if (r > 0.5) return "bg-green-500/30";
  if (r > 0) return "bg-green-500/15";
  return "";
}

/** Who is overloaded: capacity (8 h weekdays, 0 on leave) vs meetings + remaining task estimates. */
export function Workload({ departmentId, projectId }: { departmentId?: string | null; projectId?: string | null }) {
  const [start, setStart] = useState(weekStart(iso(new Date())));
  const end = addDays(start, 13);
  const q = useQuery({
    queryKey: ["workload", departmentId, projectId, start],
    queryFn: () => api.get<WorkloadRow[]>("/calendar/workload", { from: start, to: end, department_id: departmentId ?? undefined, project_id: projectId ?? undefined }),
    enabled: !!departmentId || !!projectId,
  });
  const days = Array.from({ length: 14 }, (_, i) => addDays(start, i));
  const today = iso(new Date());
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" aria-label="Previous two weeks" onClick={() => setStart(addDays(start, -14))}><ChevronLeft /></Button>
        <Button variant="outline" size="icon" aria-label="Next two weeks" onClick={() => setStart(addDays(start, 14))}><ChevronRight /></Button>
        <span className="text-sm text-muted-foreground">{fmtDay(start)} – {fmtDay(end)}</span>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="w-40 px-2 py-1.5 text-left font-medium">Person</th>
              {days.map((d) => (
                <th key={d} className={cn("px-1 py-1.5 text-center font-normal", d === today && "font-semibold text-primary")}>
                  {fmtDay(d, { weekday: "narrow" })}<br />{Number(d.slice(8))}
                </th>
              ))}
              <th className="px-2 py-1.5 text-right font-medium">Load / capacity</th>
            </tr>
          </thead>
          <tbody>
            {(q.data ?? []).map((r) => (
              <tr key={r.employee_id} className="border-b last:border-0">
                <td className="truncate px-2 py-1 font-medium">{r.employee_name}</td>
                {r.days.map((d) => {
                  const load = Number(d.load);
                  const cap = Number(d.capacity);
                  return (
                    <td key={d.date} className={cn("tabular h-8 border-l px-0.5 text-center", cellClass(load, cap, d.on_leave))}
                      title={d.on_leave ? "On leave" : `${load.toFixed(1)} h of ${cap} h · meetings ${Number(d.meetings).toFixed(1)} h · tasks ${Number(d.tasks).toFixed(1)} h`}>
                      {d.on_leave ? "L" : load ? load.toFixed(load < 10 ? 1 : 0) : ""}
                    </td>
                  );
                })}
                <td className="tabular px-2 py-1 text-right">{Number(r.load).toFixed(0)} / {Number(r.capacity).toFixed(0)} h</td>
              </tr>
            ))}
            {q.data && q.data.length === 0 && (
              <tr><td colSpan={16} className="p-4 text-center text-muted-foreground">Nobody in this team.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">Hours per day. Green = room left, orange = nearly full, red = overloaded, L = on leave. Task hours are the remaining estimate spread over the task&apos;s working days.</p>
    </div>
  );
}
