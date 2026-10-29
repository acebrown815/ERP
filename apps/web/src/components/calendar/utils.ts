/** Calendar date helpers. Dates are "YYYY-MM-DD" strings in the viewer's local time. */

export const DAY_MS = 86_400_000;

export function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function parse(s: string): Date {
  return new Date(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
}

export function addDays(s: string, n: number): string {
  const d = parse(s);
  d.setDate(d.getDate() + n);
  return iso(d);
}

/** Monday of the week containing `s`. */
export function weekStart(s: string): string {
  const d = parse(s);
  return addDays(s, -((d.getDay() + 6) % 7));
}

export function monthStart(s: string): string {
  return `${s.slice(0, 7)}-01`;
}

export function addMonths(s: string, n: number): string {
  const d = parse(monthStart(s));
  d.setMonth(d.getMonth() + n);
  return iso(d);
}

/** 6×7 grid of days covering the month of `s`, weeks starting Monday. */
export function monthGrid(s: string): string[] {
  const first = weekStart(monthStart(s));
  return Array.from({ length: 42 }, (_, i) => addDays(first, i));
}

export function between(day: string, start: string, end: string): boolean {
  return day >= start.slice(0, 10) && day <= end.slice(0, 10);
}

export const browserTimeZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

export function fmtDay(s: string, opts: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" }): string {
  return new Intl.DateTimeFormat("en-US", opts).format(parse(s));
}

export function fmtTime(isoInstant: string): string {
  return new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit" }).format(new Date(isoInstant));
}

/** Local calendar day of a UTC instant. */
export function localDay(isoInstant: string): string {
  return iso(new Date(isoInstant));
}

/** Tailwind classes per event colour (category setting). */
export const COLOR: Record<string, string> = {
  slate: "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/40",
  red: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40",
  orange: "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/40",
  amber: "bg-amber-500/20 text-amber-800 dark:text-amber-300 border-amber-500/50",
  yellow: "bg-yellow-500/20 text-yellow-800 dark:text-yellow-300 border-yellow-500/50",
  green: "bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/40",
  teal: "bg-teal-500/15 text-teal-700 dark:text-teal-300 border-teal-500/40",
  blue: "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/40",
  indigo: "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border-indigo-500/40",
  violet: "bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/40",
  pink: "bg-pink-500/15 text-pink-700 dark:text-pink-300 border-pink-500/40",
};

export function colorClass(c: string | null | undefined): string {
  return COLOR[c ?? "blue"] ?? COLOR.blue!;
}

/** Build an RFC 5545 rule from the dialog's repeat options. */
export type Repeat = { freq: "" | "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY"; byday: string[]; end: "never" | "until" | "count"; until: string; count: string };

export function toRRule(r: Repeat): string | null {
  if (!r.freq) return null;
  const parts = [`FREQ=${r.freq}`];
  if (r.freq === "WEEKLY" && r.byday.length) parts.push(`BYDAY=${r.byday.join(",")}`);
  if (r.end === "until" && r.until) parts.push(`UNTIL=${r.until.replaceAll("-", "")}`);
  if (r.end === "count" && Number(r.count) > 0) parts.push(`COUNT=${Number(r.count)}`);
  return parts.join(";");
}

export function fromRRule(rule: string | null | undefined): Repeat {
  const r: Repeat = { freq: "", byday: [], end: "never", until: "", count: "" };
  if (!rule) return r;
  for (const part of rule.split(";")) {
    const [k, v = ""] = part.split("=");
    if (k === "FREQ") r.freq = v as Repeat["freq"];
    if (k === "BYDAY") r.byday = v.split(",");
    if (k === "COUNT") {
      r.end = "count";
      r.count = v;
    }
    if (k === "UNTIL") {
      r.end = "until";
      r.until = `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}`;
    }
  }
  return r;
}

export function describeRRule(rule: string | null | undefined): string {
  const r = fromRRule(rule);
  if (!r.freq) return "Does not repeat";
  const base = { DAILY: "Daily", WEEKLY: "Weekly", MONTHLY: "Monthly", YEARLY: "Yearly" }[r.freq];
  const days = r.freq === "WEEKLY" && r.byday.length ? ` on ${r.byday.join(", ")}` : "";
  const end = r.end === "until" ? ` until ${r.until}` : r.end === "count" ? `, ${r.count} times` : "";
  return base + days + end;
}
