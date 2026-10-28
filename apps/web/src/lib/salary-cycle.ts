/**
 * Salary period preview (docs/architecture.md, Section 10.1). A period is labelled by the month it
 * ends in: with start day 25, "Nov 2026" runs Oct 25 – Nov 24. Start day 1 = calendar month.
 * The server owns real period generation (Phase 3); this is display-only.
 */

export type SalaryPeriod = { label: string; start: Date; end: Date };

const utc = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d));

export function salaryPeriodFor(year: number, month: number /* 0-11, the month the period ends in */, startDay: number): SalaryPeriod {
  if (!Number.isInteger(startDay) || startDay < 1 || startDay > 28) throw new RangeError("startDay must be 1-28");
  const label = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" }).format(utc(year, month, 1));
  if (startDay === 1) return { label, start: utc(year, month, 1), end: utc(year, month + 1, 0) };
  return { label, start: utc(year, month - 1, startDay), end: utc(year, month, startDay - 1) };
}

export function upcomingPeriods(today: Date, startDay: number, count = 3): SalaryPeriod[] {
  // The current period is the one whose end date is on/after today.
  const y = today.getUTCFullYear();
  let m = today.getUTCMonth();
  if (startDay !== 1 && today.getUTCDate() >= startDay) m += 1;
  const out: SalaryPeriod[] = [];
  for (let i = 0; i < count; i++) {
    const d = utc(y, m + i, 1);
    out.push(salaryPeriodFor(d.getUTCFullYear(), d.getUTCMonth(), startDay));
  }
  return out;
}

export function formatPeriodRange(p: SalaryPeriod): string {
  const f = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return `${f.format(p.start)} – ${f.format(p.end)}`;
}
