export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { timeStyle: "short" });
}

/** ISO instant -> value for <input type="datetime-local"> in the browser's time zone. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** <input type="datetime-local"> value (browser time zone) -> ISO instant with offset (UTC). */
export function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "Thursday, Oct 24, 2025": browser locale and time zone. */
export function formatDateLong(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** "9:00 AM PST": start time with the browser's zone abbreviation. */
export function formatTimeZoned(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** "09:14:22" (audit-log style times at the door). */
export function formatTimeSeconds(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** part/total as a percentage with at most one decimal; 0 when total is 0; capped at 100. */
export function percent(part: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((part / total) * 1000) / 10);
}

export function formatPercent(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

export type CapacityTier = "available" | "high" | "full";

/** How full an event is, for the availability bar: sold out -> full; >= 80% taken -> high demand. */
export function capacityTier(capacity: number, seatsLeft: number): CapacityTier {
  if (seatsLeft <= 0) return "full";
  return percent(capacity - seatsLeft, capacity) >= 80 ? "high" : "available";
}

export type Countdown = { started: boolean; days: number; hours: number; minutes: number };

export function countdown(startsAtIso: string, nowMs: number): Countdown {
  const diff = new Date(startsAtIso).getTime() - nowMs;
  if (diff <= 0) return { started: true, days: 0, hours: 0, minutes: 0 };
  const totalMinutes = Math.floor(diff / 60_000);
  return {
    started: false,
    days: Math.floor(totalMinutes / 1440),
    hours: Math.floor((totalMinutes % 1440) / 60),
    minutes: totalMinutes % 60,
  };
}

/** "just now", "5 min ago", "3 h ago", "2 d ago". */
export function timeAgo(iso: string, nowMs: number): string {
  const seconds = Math.max(0, Math.floor((nowMs - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86_400)} d ago`;
}

/** Up to two initials from a title ("PyCon Meetup" -> "PM"); first letter for an email. */
export function initialsOf(text: string): string {
  const words = text
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .map((w) => w[0]?.toUpperCase() ?? "");
  return (text.includes("@") ? words.slice(0, 1) : words.slice(0, 2)).join("") || "?";
}
