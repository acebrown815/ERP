"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/erp/confirm-dialog";
import { FormField } from "@/components/erp/form-field";
import { PageHeader } from "@/components/erp/page-header";
import { ErrorState } from "@/components/erp/states";
import { periodRange } from "@/components/salary/shared";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";
import { useCan } from "@/lib/session";
import type { SalaryCycle } from "@/lib/types";
import { ordinal } from "@/lib/utils";

type Span = SalaryCycle["upcoming"][number];

function Spans({ current, upcoming }: { current: Span | null | undefined; upcoming: Span[] }) {
  return (
    <ul className="flex flex-col divide-y rounded-md border text-sm">
      {current && (
        <li className="flex items-center justify-between gap-3 px-3 py-2">
          <span className="font-medium">{current.label} <Badge variant="muted" className="ml-1">current, unchanged</Badge></span>
          <span className="tabular text-muted-foreground">{periodRange(current)}</span>
        </li>
      )}
      {upcoming.map((s) => (
        <li key={s.start_date} className="flex items-center justify-between gap-3 px-3 py-2">
          <span className="font-medium">{s.label.replace(" (transition)", "")} {s.is_transition && <Badge variant="warning" className="ml-1">transition</Badge>}</span>
          <span className="tabular text-muted-foreground">{periodRange(s)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function SalaryCyclePage() {
  const qc = useQueryClient();
  const can = useCan();
  const editable = can("salary.configure_cycle");
  const cycle = useQuery({ queryKey: ["salary-cycle"], queryFn: () => api.get<SalaryCycle>("/settings/salary-cycle") });
  const [day, setDay] = useState<number | null>(null);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    if (cycle.data && day === null) setDay(cycle.data.salary_cycle_start_day);
  }, [cycle.data, day]);
  const changed = cycle.data && day !== null && day !== cycle.data.salary_cycle_start_day;
  const plan = useQuery({
    queryKey: ["salary-cycle-preview", day],
    queryFn: () => api.post<SalaryCycle>("/settings/salary-cycle/preview", { salary_cycle_start_day: day }),
    enabled: !!changed && editable,
    placeholderData: keepPreviousData,
  });
  const save = useMutation({
    mutationFn: () => api.put<SalaryCycle>("/settings/salary-cycle", { salary_cycle_start_day: day }),
    onSuccess: (c) => {
      qc.setQueryData(["salary-cycle"], c);
      qc.invalidateQueries({ queryKey: ["company"] });
      qc.invalidateQueries({ queryKey: ["salary-periods"] });
      toast.success(`Salary periods now start on the ${ordinal(c.salary_cycle_start_day)}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not save"),
  });

  if (cycle.isError) return <ErrorState error={cycle.error} onRetry={() => cycle.refetch()} />;
  if (!cycle.data || day === null) return <Skeleton className="h-64 w-full" />;
  const c = cycle.data;
  const p = changed ? plan.data : undefined;

  return (
    <>
      <PageHeader
        title="Salary cycle"
        description="Employee revenue and salary are counted per salary period. Accounting periods, the P&L and the balance sheet stay on calendar months."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Start day</CardTitle>
            <CardDescription>A period is named after the month it ends in: with the 25th, &quot;Nov&quot; runs Oct 25 – Nov 24.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <FormField id="day" label="Periods start on" hint="1 = calendar months. Days 29–31 aren't offered so every month has the day.">
              <Select id="day" value={day} disabled={!editable} onChange={(e) => setDay(Number(e.target.value))}>
                {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>{d === 1 ? "1st (calendar month)" : `the ${ordinal(d)}`}</option>
                ))}
              </Select>
            </FormField>
            {!editable && <p className="text-sm text-muted-foreground">Only administrators can change the salary cycle.</p>}
            {editable && changed && (
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDay(c.salary_cycle_start_day)}>Reset</Button>
                <Button disabled={!p || p.blockers.length > 0} onClick={() => setConfirm(true)}>Apply</Button>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{changed ? "After the change" : "Periods"}</CardTitle>
            <CardDescription>
              {changed
                ? p?.replaces_all
                  ? "Nothing depends on the current periods yet (no closed periods, adjustments or salary payments), so they are all regenerated."
                  : "Periods that have started keep their dates. A shorter transition period bridges to the new day if needed."
                : "The current period and the next ones."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {changed && !p ? <Skeleton className="h-40 w-full" /> : <Spans current={(p ?? c).current} upcoming={(p ?? c).upcoming} />}
            {p?.blockers.map((b) => (
              <p key={b} role="alert" className="flex items-start gap-2 text-sm text-destructive"><AlertTriangle className="mt-0.5 size-4 shrink-0" /> {b}</p>
            ))}
          </CardContent>
        </Card>
      </div>
      {confirm && p && (
        <ConfirmDialog
          open
          onOpenChange={setConfirm}
          title={`Start salary periods on the ${ordinal(day)}?`}
          description={p.upcoming.some((s) => s.is_transition)
            ? `The next period, ${periodRange(p.upcoming[0]!)}, is a shorter transition period. Revenue in it is paid with the normal formula.`
            : "Upcoming periods are regenerated with the new day."}
          confirmLabel="Apply"
          onConfirm={() => save.mutateAsync()}
        />
      )}
    </>
  );
}
