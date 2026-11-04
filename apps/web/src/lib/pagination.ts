export type PageItem = number | "gap";

/** Page buttons to show: first, last and the pages around the current one, with gaps. A gap of one page is filled in. */
export function pageItems(page: number, lastPage: number, around = 1): PageItem[] {
  const wanted = new Set([1, lastPage]);
  for (let p = page - around; p <= page + around; p++) {
    if (p >= 1 && p <= lastPage) wanted.add(p);
  }
  const items: PageItem[] = [];
  let previous = 0;
  for (const p of [...wanted].sort((a, b) => a - b)) {
    if (p - previous === 2) items.push(p - 1);
    else if (p - previous > 2) items.push("gap");
    items.push(p);
    previous = p;
  }
  return items;
}

/** A typed page number as a page to open, or null if it isn't a whole number. Out-of-range values go to the nearest page. */
export function parsePageInput(value: string, lastPage: number): number | null {
  const text = value.trim();
  if (!/^\d+$/.test(text)) return null;
  return Math.min(Math.max(Number(text), 1), lastPage);
}
