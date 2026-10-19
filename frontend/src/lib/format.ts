export const fmtBytes = (n: number): string => {
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"]; let v = n / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${u[i]}`;
};
export const fmtNum = (n: number) => new Intl.NumberFormat("en").format(n);
export const fmtEur = (cents: number, frac = 0) => new Intl.NumberFormat("en", { style: "currency", currency: "EUR", minimumFractionDigits: frac, maximumFractionDigits: frac }).format(cents / 100);
export const fmtDate = (s?: string | null) => s ? new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
export const fmtDay = (s?: string | null) => s ? new Date(s).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
export function ago(s?: string | null): string {
  if (!s) return "—";
  const d = (Date.now() - new Date(s).getTime()) / 1000;
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  if (d < 86400 * 30) return `${Math.round(d / 86400)} d ago`;
  return fmtDay(s);
}
export const short = (s: string, n = 12) => (s.length > n ? s.slice(0, n) + "…" : s);
export const titleCase = (s: string) => s.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
export const planPrice = (p: { price_month_cents: number | null; contact_sales: boolean }) =>
  p.contact_sales || p.price_month_cents === null ? "Contact sales" : p.price_month_cents === 0 ? "€0" : `€${p.price_month_cents / 100}`;
