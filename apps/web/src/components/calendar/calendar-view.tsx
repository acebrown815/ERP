"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight, Diamond, Flag, ListChecks, Plus, Repeat } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { CalendarFeed, FeedItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useMe } from "@/lib/session";

import { EventDialog, type EventDefaults } from "./event-dialog";
import { addDays, addMonths, between, colorClass, fmtDay, fmtTime, iso, localDay, monthGrid, monthStart, weekStart } from "./utils";

type Mode = "month" | "week" | "agenda";
const HOUR = 44;

function Icon({ item }: { item: FeedItem }) {
  if (item.kind === "task") return <ListChecks className="size-3 shrink-0" />;
  if (item.kind === "milestone") return <Diamond className="size-3 shrink-0" />;
  if (item.kind === "deadline") return <Flag className="size-3 shrink-0" />;
  if (item.recurring) return <Repeat className="size-3 shrink-0" />;
  return null;
}

function Chip({ item, people, onOpen }: { item: FeedItem; people: Record<string, string>; onOpen: (i: FeedItem) => void }) {
  const who = item.kind === "leave" ? item.employee_ids.map((e) => people[e]).filter(Boolean).join(", ") : "";
  return (
    <button
      type="button"
      onClick={(ev) => {
        ev.stopPropagation();
        onOpen(item);
      }}
      className={cn(
        "flex w-full items-center gap-1 truncate rounded border px-1 py-0.5 text-left text-[11px] leading-tight",
        colorClass(item.color),
        item.status === "requested" && "border-dashed opacity-80",
        item.status === "done" && "line-through opacity-60",
      )}
      title={`${item.title}${who ? ` · ${who}` : ""}${item.project_name ? ` · ${item.project_name}` : ""}${item.status === "requested" ? " · awaiting approval" : ""}`}
    >
      <Icon item={item} />
      {!item.all_day && <span className="tabular shrink-0 opacity-75">{fmtTime(item.start)}</span>}
      <span className="truncate">{item.kind === "leave" && who ? `${who}: ${item.title}` : item.title}</span>
    </button>
  );
}

/** Items touching a day: all-day spans, or timed items starting that (local) day. */
function onDay(items: FeedItem[], day: string): FeedItem[] {
  return items.filter((i) => (i.all_day ? between(day, i.start, i.end) : localDay(i.start) === day));
}

export function CalendarView({
  view,
  departmentId,
  projectId,
  defaults,
  title,
}: {
  view: "me" | "team" | "company";
  departmentId?: string | null;
  projectId?: string | null;
  defaults?: EventDefaults;
  title?: React.ReactNode;
}) {
  const router = useRouter();
  const isHire = useMe().restricted_access;
  const today = iso(new Date());
  const [mode, setMode] = useState<Mode>("month");
  const [anchor, setAnchor] = useState(today);
  const [open, setOpen] = useState<{ eventId?: string; occurrence?: string | null; date?: string; leave?: boolean } | null>(null);
  const range =
    mode === "month"
      ? { from: monthGrid(anchor)[0]!, to: monthGrid(anchor)[41]! }
      : mode === "week"
        ? { from: weekStart(anchor), to: addDays(weekStart(anchor), 6) }
        : { from: anchor, to: addDays(anchor, 30) };
  const feed = useQuery({
    queryKey: ["calendar", view, departmentId, projectId, range.from, range.to],
    queryFn: () =>
      api.get<CalendarFeed>("/calendar/feed", { from: range.from, to: range.to, view, department_id: departmentId ?? undefined, project_id: projectId ?? undefined }),
    placeholderData: keepPreviousData,
    enabled: view !== "team" || !!departmentId || !!projectId,
  });
  const items = feed.data?.items ?? [];
  const people = feed.data?.people ?? {};
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (mode === "week" && scroller.current) scroller.current.scrollTop = HOUR * 7;
  }, [mode]);

  const openItem = (i: FeedItem) => {
    if (i.kind === "event" || i.kind === "leave") setOpen({ eventId: i.id, occurrence: i.occurrence });
    else if (i.link) router.push(i.link);
  };
  const step = (n: number) => setAnchor(mode === "month" ? addMonths(anchor, n) : addDays(anchor, n * (mode === "week" ? 7 : 30)));
  const heading =
    mode === "month"
      ? new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" }).format(new Date(`${monthStart(anchor)}T12:00:00`))
      : `${fmtDay(range.from, { day: "numeric", month: "short" })} – ${fmtDay(range.to, { day: "numeric", month: "short", year: "numeric" })}`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="icon" aria-label="Previous" onClick={() => step(-1)}><ChevronLeft /></Button>
        <Button variant="outline" size="sm" onClick={() => setAnchor(today)}>Today</Button>
        <Button variant="outline" size="icon" aria-label="Next" onClick={() => step(1)}><ChevronRight /></Button>
        <h2 className="ml-1 text-lg font-semibold">{heading}</h2>
        {title}
        <div className="ml-auto flex flex-wrap gap-2">
          <div className="flex gap-1 rounded-md border p-0.5 text-sm" role="radiogroup" aria-label="View">
            {(["month", "week", "agenda"] as const).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
                className={cn("rounded px-2.5 py-1 capitalize", mode === m ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground")}>
                {m}
              </button>
            ))}
          </div>
          {/* A hired manager's calendar shows their tasks and project dates; they don't add to it. */}
          {view === "me" && !isHire && <Button variant="outline" size="sm" onClick={() => setOpen({ date: today, leave: true })}><CalendarDays /> Request leave</Button>}
          {!isHire && <Button size="sm" onClick={() => setOpen({ date: mode === "month" ? today : range.from < today && today <= range.to ? today : range.from })}><Plus /> New event</Button>}
        </div>
      </div>

      {mode === "month" && (
        <div className="overflow-hidden rounded-lg border">
          <div className="grid grid-cols-7 border-b bg-muted/50 text-xs font-medium text-muted-foreground">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="px-2 py-1.5">{d}</div>)}
          </div>
          <div className="grid grid-cols-7">
            {monthGrid(anchor).map((day) => {
              const list = onDay(items, day);
              const inMonth = day.slice(0, 7) === anchor.slice(0, 7);
              return (
                <div key={day} role="button" tabIndex={0} onClick={() => setOpen({ date: day })} onKeyDown={(ev) => ev.key === "Enter" && setOpen({ date: day })}
                  className={cn("min-h-24 border-b border-r p-1 text-left align-top hover:bg-muted/40", !inMonth && "bg-muted/30 text-muted-foreground")}
                  aria-label={`${fmtDay(day)}: ${list.length} item(s). Add event`}>
                  <div className={cn("mb-1 flex size-6 items-center justify-center rounded-full text-xs", day === today && "bg-primary font-semibold text-primary-foreground")}>
                    {Number(day.slice(8))}
                  </div>
                  <div className="flex flex-col gap-0.5">
                    {list.slice(0, 4).map((i) => <Chip key={i.key} item={i} people={people} onOpen={openItem} />)}
                    {list.length > 4 && (
                      <button type="button" className="text-left text-[11px] text-muted-foreground hover:underline"
                        onClick={(ev) => { ev.stopPropagation(); setAnchor(day); setMode("week"); }}>
                        +{list.length - 4} more
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {mode === "week" && (() => {
        const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart(anchor), i));
        return (
          <div className="overflow-hidden rounded-lg border">
            <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b bg-muted/50 text-xs">
              <div />
              {days.map((d) => (
                <div key={d} className={cn("px-2 py-1.5 font-medium", d === today && "text-primary")}>{fmtDay(d)}</div>
              ))}
            </div>
            <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b">
              <div className="px-1 py-1 text-[10px] text-muted-foreground">All day</div>
              {days.map((d) => (
                <div key={d} className="flex min-h-8 flex-col gap-0.5 border-l p-0.5">
                  {onDay(items, d).filter((i) => i.all_day).map((i) => <Chip key={i.key} item={i} people={people} onOpen={openItem} />)}
                </div>
              ))}
            </div>
            <div ref={scroller} className="relative max-h-[32rem] overflow-y-auto">
              <div className="grid grid-cols-[3.5rem_repeat(7,1fr)]" style={{ height: HOUR * 24 }}>
                <div className="relative">
                  {Array.from({ length: 24 }, (_, h) => (
                    <div key={h} className="absolute right-1 text-[10px] text-muted-foreground" style={{ top: h * HOUR - 6 }}>{h ? `${String(h).padStart(2, "0")}:00` : ""}</div>
                  ))}
                </div>
                {days.map((d) => (
                  <div key={d} className="relative border-l" onClick={() => setOpen({ date: d })}>
                    {Array.from({ length: 24 }, (_, h) => <div key={h} className="border-b border-dashed border-border/60" style={{ height: HOUR }} />)}
                    {onDay(items, d).filter((i) => !i.all_day).map((i) => {
                      const s = new Date(i.start);
                      const e = new Date(i.end);
                      const top = (s.getHours() + s.getMinutes() / 60) * HOUR;
                      const height = Math.max(((e.getTime() - s.getTime()) / 3_600_000) * HOUR, 18);
                      return (
                        <div key={i.key} className="absolute inset-x-0.5" style={{ top, height }}>
                          <button type="button" onClick={(ev) => { ev.stopPropagation(); openItem(i); }}
                            className={cn("h-full w-full overflow-hidden rounded border px-1 text-left text-[11px]", colorClass(i.color))}>
                            <span className="tabular block opacity-75">{fmtTime(i.start)}–{fmtTime(i.end)}</span>
                            <span className="block truncate font-medium">{i.title}</span>
                          </button>
                        </div>
                      );
                    })}
                    {d === today && (
                      <div className="pointer-events-none absolute inset-x-0 h-0.5 bg-primary" style={{ top: (new Date().getHours() + new Date().getMinutes() / 60) * HOUR }} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        );
      })()}

      {mode === "agenda" && (
        <div className="divide-y rounded-lg border">
          {Array.from({ length: 31 }, (_, i) => addDays(anchor, i)).map((d) => {
            const list = onDay(items, d);
            if (!list.length) return null;
            return (
              <div key={d} className="grid gap-2 p-3 sm:grid-cols-[9rem_1fr]">
                <div className={cn("text-sm font-medium", d === today && "text-primary")}>{fmtDay(d, { weekday: "long", day: "numeric", month: "short" })}</div>
                <div className="flex flex-col gap-1">
                  {list.map((i) => <Chip key={i.key} item={i} people={people} onOpen={openItem} />)}
                </div>
              </div>
            );
          })}
          {!items.length && <p className="p-6 text-sm text-muted-foreground">Nothing in the next 30 days.</p>}
        </div>
      )}

      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1"><ListChecks className="size-3" /> Task (from Projects)</span>
        <span className="flex items-center gap-1"><Diamond className="size-3" /> Milestone</span>
        <span className="flex items-center gap-1"><Flag className="size-3" /> Project deadline</span>
        <span className="flex items-center gap-1"><Repeat className="size-3" /> Repeats</span>
        <span className="flex items-center gap-1"><span className="inline-block h-3 w-5 rounded border border-dashed" /> Awaiting approval</span>
        Tasks and milestones come straight from projects: change their dates there.
      </p>
      {open && (
        <EventDialog
          key={open.eventId ?? `new-${open.date}-${open.leave}`}
          eventId={open.eventId}
          occurrence={open.occurrence}
          defaults={{ ...defaults, date: open.date, leave: open.leave }}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}
