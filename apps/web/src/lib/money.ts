/**
 * Money is a decimal string end to end (API sends "10000.0000"). These helpers format and compare
 * without converting to floating point, so 18-decimal crypto amounts stay exact.
 */

const DECIMAL_RE = /^-?\d+(\.\d+)?$/;

export function isDecimal(value: string): boolean {
  return DECIMAL_RE.test(value.trim());
}

/** Number of decimal places in a user-entered amount. */
export function decimals(value: string): number {
  const frac = value.trim().split(".")[1];
  return frac ? frac.length : 0;
}

/** Format "1234567.5" as "1,234,567.50" (fixed `precision`, half-up rounding on the string). */
export function formatAmount(value: string | number | null | undefined, precision = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  let text = String(value).trim();
  if (!isDecimal(text)) return text;
  const negative = text.startsWith("-");
  if (negative) text = text.slice(1);
  let [int = "0", frac = ""] = text.split(".");
  if (frac.length > precision) {
    const roundUp = Number(frac[precision]) >= 5;
    frac = frac.slice(0, precision);
    if (roundUp) {
      const digits = (int + frac).split("").map(Number);
      let i = digits.length - 1;
      while (i >= 0) {
        if (digits[i]! < 9) {
          digits[i]! += 1;
          break;
        }
        digits[i] = 0;
        i--;
      }
      const joined = (i < 0 ? "1" : "") + digits.join("");
      int = joined.slice(0, joined.length - precision) || "0";
      frac = joined.slice(joined.length - precision);
    }
  }
  frac = frac.padEnd(precision, "0");
  int = int.replace(/^0+(?=\d)/, "");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const isZero = /^0*$/.test(int + frac);
  return `${negative && !isZero ? "-" : ""}${grouped}${precision ? `.${frac}` : ""}`;
}

export function formatMoney(value: string | number | null | undefined, currency: string, precision = 2): string {
  const formatted = formatAmount(value, precision);
  return formatted === "—" ? formatted : `${formatted} ${currency}`;
}

/** Sign of a decimal string: -1, 0 or 1. */
export function sign(value: string | null | undefined): number {
  if (!value || !isDecimal(value)) return 0;
  if (/^-?0*(\.0*)?$/.test(value.trim())) return 0;
  return value.trim().startsWith("-") ? -1 : 1;
}

/** Exact sum of decimal strings (BigInt on scaled integers). */
export function sum(values: (string | null | undefined)[], scale = 18): string {
  let total = BigInt(0);
  for (const v of values) {
    if (!v || !isDecimal(v)) continue;
    const negative = v.trim().startsWith("-");
    const [int = "0", frac = ""] = v.trim().replace("-", "").split(".");
    const scaled = BigInt(int + frac.padEnd(scale, "0").slice(0, scale));
    total += negative ? -scaled : scaled;
  }
  const negative = total < BigInt(0);
  const digits = (negative ? -total : total).toString().padStart(scale + 1, "0");
  const out = `${digits.slice(0, -scale)}.${digits.slice(-scale)}`.replace(/\.?0+$/, "");
  return `${negative ? "-" : ""}${out || "0"}`;
}
