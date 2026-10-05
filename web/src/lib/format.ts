import type { Json } from "./contracts";

export function label(value: string): string {
  return value
    .replace(/[_\.]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bPnl\b/g, "P&L");
}
export function dateTime(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Invalid timestamp";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
export function relativeTime(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const elapsed = (Date.now() - new Date(value).getTime()) / 1000;
  if (!Number.isFinite(elapsed)) return "Invalid timestamp";
  if (elapsed < 60) return "Just now";
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)}h ago`;
  return `${Math.floor(elapsed / 86400)}d ago`;
}
export function money(value: string | number | null | undefined): string {
  if (value == null || value === "" || !Number.isFinite(Number(value)))
    return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value));
}
export function scalar(value: Json | undefined): string {
  if (value == null) return "—";
  if (typeof value === "number")
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 6 });
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return JSON.stringify(value);
}
export function duration(ms: number | null): string {
  if (ms == null) return "Not recorded";
  return ms < 1000
    ? `${ms} ms`
    : ms < 60_000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${(ms / 60_000).toFixed(1)} min`;
}
export function isRecord(value: unknown): value is Record<string, Json> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
export function displayJson(value: unknown): string {
  return typeof value === "string"
    ? value
    : (JSON.stringify(value, null, 2) ?? "null");
}
