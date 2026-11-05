/** Time ranges for reports. A "month" is a salary period (Settings → Salary Cycle), e.g. Oct 25 – Nov 24. */

export type Range = { from: string; to: string };
export type PresetKey = "this_month" | "last_month" | "last_3" | "last_6" | "this_year" | "all_time";
export type RangePreset = { key: PresetKey; label: string; range: Range };

type Period = { start_date: string; end_date: string; is_current: boolean; is_future: boolean };

/** Earlier than anything in the books, so "All time" can't leave out entries dated before the first salary period. */
export const ALL_TIME_FROM = "2000-01-01";

export function monthRange(d = new Date()): Range {
  const from = new Date(Date.UTC(d.getFullYear(), d.getMonth(), 1));
  const to = new Date(Date.UTC(d.getFullYear(), d.getMonth() + 1, 0));
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

export function yearRange(d = new Date()): Range {
  return { from: `${d.getFullYear()}-01-01`, to: `${d.getFullYear()}-12-31` };
}

/**
 * The ranges to offer, given the salary periods (newest first). "Last N months" include the current one, as the
 * other reports do, and are left out until there are N periods. Without periods: the calendar month.
 */
export function rangePresets(periods: Period[], today = new Date()): RangePreset[] {
  const started = periods.filter((p) => !p.is_future);
  const i = started.findIndex((p) => p.is_current);
  const current = started[i];
  const end = current?.end_date ?? monthRange(today).to;
  const lastN = (key: PresetKey, n: number): RangePreset[] => {
    const first = started[i + n - 1];
    return current && first ? [{ key, label: `Last ${n} months`, range: { from: first.start_date, to: end } }] : [];
  };
  const previous = current ? started[i + 1] : undefined;
  return [
    { key: "this_month", label: "This month", range: current ? { from: current.start_date, to: current.end_date } : monthRange(today) },
    ...(previous ? [{ key: "last_month" as const, label: "Last month", range: { from: previous.start_date, to: previous.end_date } }] : []),
    ...lastN("last_3", 3),
    ...lastN("last_6", 6),
    { key: "this_year", label: "This year", range: yearRange(today) },
    { key: "all_time", label: "All time", range: { from: ALL_TIME_FROM, to: end } },
  ];
}

/** Which preset these dates are, if any: the dates are what counts, however they were chosen. */
export function matchPreset(presets: RangePreset[], r: Range): PresetKey | undefined {
  return presets.find((p) => p.range.from === r.from && p.range.to === r.to)?.key;
}
