const inrFmt = (digits: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: digits, maximumFractionDigits: digits });
const whole = inrFmt(0);
const cents = inrFmt(2);

export const inr = (value: number, precise = false) => (precise ? cents : whole).format(value);
export const signedInr = (value: number, precise = true) => (value > 0 ? "+" : "") + inr(value, precise);
export const sym = (symbol: string) => symbol.replace(".NS", "").replace("-EQ", "");
export const tone = (value: number | null | undefined) => (value == null ? "" : value >= 0 ? "pos" : "neg");
export const pct = (value: number, digits = 1) => `${value.toFixed(digits)}%`;

export const when = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
export const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
export const reason = (text: string | null | undefined) => (text ?? "").split(" (")[0].replaceAll("_", " ") || "—";
