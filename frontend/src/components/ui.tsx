import type { ReactNode } from "react";
import type { StreamStatus } from "../useEventStream";
import { Icon } from "./Icon";

export type Tone = "ok" | "warn" | "error" | "neutral" | "primary";

// Status chips from DESIGN.md: emerald = confirmed/live, amber = waitlist/low stock, rose = error/sold out.
const TONE: Record<Tone, { box: string; dot: string }> = {
  ok: { box: "bg-secondary-container text-on-secondary-container", dot: "bg-secondary" },
  warn: { box: "bg-tertiary-fixed text-on-tertiary-fixed-variant", dot: "bg-tertiary" },
  error: { box: "bg-error-container text-on-error-container", dot: "bg-error" },
  neutral: { box: "bg-surface-container-high text-on-surface-variant", dot: "bg-outline" },
  primary: { box: "bg-primary-fixed text-on-primary-fixed", dot: "bg-primary" },
};

export function Pill({
  tone = "neutral",
  dot = false,
  pulse = false,
  className = "",
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-label-sm text-label-sm whitespace-nowrap ${TONE[tone].box} ${className}`}
    >
      {dot && <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${TONE[tone].dot} ${pulse ? "animate-pulse" : ""}`} />}
      {children}
    </span>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div role="status" className="flex items-center gap-space-sm py-space-lg text-on-surface-variant font-body-md text-body-md">
      <span aria-hidden="true" className="inline-block w-4 h-4 rounded-full border-2 border-outline-variant border-t-primary animate-spin" />
      {what}…
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-space-sm p-3 rounded-lg bg-error-container text-on-error-container font-body-md text-body-md">
      <Icon name="error" filled className="text-error text-[20px] shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const NOTICE: Record<"info" | "ok" | "warn", { box: string; icon: string; iconColor: string }> = {
  info: { box: "bg-primary-fixed text-on-primary-fixed", icon: "info", iconColor: "text-primary" },
  ok: { box: "bg-secondary-container/50 text-on-secondary-fixed", icon: "check_circle", iconColor: "text-secondary" },
  warn: { box: "bg-tertiary-fixed/50 text-on-tertiary-fixed", icon: "hourglass_top", iconColor: "text-tertiary" },
};

export function Notice({ kind = "info", children }: { kind?: "info" | "ok" | "warn"; children: ReactNode }) {
  const n = NOTICE[kind];
  return (
    <div role="status" className={`flex items-start gap-space-sm p-3 rounded-lg font-body-md text-body-md ${n.box}`}>
      <Icon name={n.icon} filled className={`${n.iconColor} text-[20px] shrink-0`} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const LIVE_TEXT: Record<StreamStatus, string> = {
  connecting: "connecting…",
  live: "live",
  reconnecting: "reconnecting…",
  expired: "login expired",
  closed: "live updates unavailable",
};
const LIVE_TONE: Record<StreamStatus, Tone> = {
  connecting: "neutral",
  live: "ok",
  reconnecting: "warn",
  expired: "error",
  closed: "error",
};

/** Live-connection pill (pulsing dot while connected). */
export function LiveBadge({ status }: { status: StreamStatus }) {
  return (
    <span aria-label={`Live updates: ${LIVE_TEXT[status]}`}>
      <Pill tone={LIVE_TONE[status]} dot pulse={status === "live"}>
        <span aria-hidden="true" className="capitalize">{LIVE_TEXT[status]}</span>
      </Pill>
    </span>
  );
}
