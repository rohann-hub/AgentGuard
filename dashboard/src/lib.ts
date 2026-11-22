// Pure helpers the views share. Kept free of React so they are easy to test.

import type { AuditEvent, Finding } from "./api";

export function isSecurityEvent(e: AuditEvent): boolean {
  return e.firewall.length > 0 || e.decision === "deny" || e.status === "blocked";
}

export function countFindings(events: AuditEvent[]): { type: string; action: string; n: number }[] {
  const counts = new Map<string, { type: string; action: string; n: number }>();
  for (const e of events) {
    for (const f of e.firewall as Finding[]) {
      const key = `${f.entity_type}:${f.action}`;
      const row = counts.get(key) ?? { type: f.entity_type, action: f.action, n: 0 };
      row.n += 1;
      counts.set(key, row);
    }
  }
  return [...counts.values()].sort((a, b) => b.n - a.n || a.type.localeCompare(b.type));
}

const time = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function formatTime(iso: string): string {
  return time.format(new Date(iso));
}

export function relative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  const [value, unit] =
    abs < 60
      ? [seconds, "second"]
      : abs < 3600
        ? [Math.round(seconds / 60), "minute"]
        : abs < 86400
          ? [Math.round(seconds / 3600), "hour"]
          : [Math.round(seconds / 86400), "day"];
  return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(
    value,
    unit as Intl.RelativeTimeFormatUnit,
  );
}

export function shortHash(hash: string | null): string {
  return hash ? `${hash.slice(0, 10)}…` : "none";
}

export const DECISION_LABEL: Record<string, string> = {
  allow: "Allowed",
  deny: "Denied",
  approval_required: "Needs approval",
};

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "none";
  if (typeof value === "number") return value.toLocaleString("en-IN");
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
