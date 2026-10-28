/** Same algorithm as the API's tasks/rank.py: a string strictly between a and b (either may be absent). */
const ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz";
const BASE = ALPHABET.length;

export function rankBetween(a: string | null | undefined, b: string | null | undefined): string {
  const lo = a ?? "";
  let hi: string | null = b ?? null;
  if (hi !== null && lo >= hi) throw new RangeError(`ranks out of order: ${lo} >= ${hi}`);
  let out = "";
  for (let i = 0; ; i++) {
    const ca = i < lo.length ? ALPHABET.indexOf(lo[i]!) : 0;
    const cb = hi !== null && i < hi.length ? ALPHABET.indexOf(hi[i]!) : BASE;
    if (ca === cb) {
      out += ALPHABET[ca];
      continue;
    }
    const mid = Math.floor((ca + cb) / 2);
    if (mid > ca) return out + ALPHABET[mid];
    out += ALPHABET[ca];
    hi = null;
  }
}
