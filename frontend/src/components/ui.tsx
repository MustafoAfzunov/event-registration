import type { ReactNode } from "react";
import type { StreamStatus } from "../useEventStream";

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted" role="status">{what}…</p>;
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <p className="alert alert-error" role="alert">{children}</p>;
}

export function Notice({ kind = "info", children }: { kind?: "info" | "ok" | "warn"; children: ReactNode }) {
  return <div className={`alert alert-${kind}`} role="status">{children}</div>;
}

const LIVE_TEXT: Record<StreamStatus, string> = {
  connecting: "connecting…",
  live: "live",
  reconnecting: "reconnecting…",
  expired: "login expired",
  closed: "live updates unavailable",
};

export function LiveBadge({ status }: { status: StreamStatus }) {
  return (
    <span className={`live live-${status}`} aria-label={`Live updates: ${LIVE_TEXT[status]}`}>
      ● {LIVE_TEXT[status]}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-value" aria-label={label}>{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
