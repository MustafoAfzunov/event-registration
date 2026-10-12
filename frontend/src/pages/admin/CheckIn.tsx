import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, streams, type AdminRegistration, type CheckInResult, type PublicEvent, type Stats } from "../../api";
import { Icon } from "../../components/Icon";
import { adminContainer, btnPrimary, card, labelSm } from "../../components/styles";
import { ErrorBox, LiveBadge, Loading, Pill } from "../../components/ui";
import { messageFor } from "../../errors";
import { formatDateLong, formatPercent, formatTimeSeconds, formatTimeZoned, percent } from "../../format";
import { useEventStream } from "../../useEventStream";

type Variant = "success" | "error" | "warning";
type Outcome =
  | { variant: "success"; result: CheckInResult; code: string }
  | { variant: "error" | "warning"; title: string; detail: string; chip: string; code: string };

function describeError(err: unknown, code: string): Outcome {
  if (err instanceof ApiError) {
    const email = typeof err.details.email === "string" ? err.details.email : "";
    switch (err.code) {
      case "already_checked_in": {
        const at = typeof err.details.checked_in_at === "string" ? formatTimeSeconds(err.details.checked_in_at) : "?";
        return { variant: "error", title: "Already used", chip: "Conflict detected", code, detail: `This ticket was checked in at ${at}${email ? ` (${email})` : ""}.` };
      }
      case "ticket_cancelled":
        return { variant: "warning", title: "Ticket cancelled", chip: "Voided", code, detail: `${email || "This person"} cancelled their registration.` };
      case "ticket_waitlisted":
        return { variant: "warning", title: "No seat (waitlist)", chip: "No seat", code, detail: `${email || "This person"} is on the waitlist.` };
      case "ticket_not_found":
        return { variant: "error", title: "Unknown code", chip: "Not found", code, detail: "No ticket with this code for this event." };
      case "invalid_code_format":
        return { variant: "warning", title: "Not a ticket code", chip: "Check the code", code, detail: "Codes have 8 letters/digits, e.g. ABCD-EFGH." };
    }
  }
  return { variant: "error", title: "Check-in failed", chip: "Error", code, detail: messageFor(err) };
}

const STRIPE: Record<Variant, string> = { success: "bg-secondary", error: "bg-error", warning: "bg-tertiary" };

function ResultCard({ outcome }: { outcome: Outcome }) {
  const ok = outcome.variant === "success";
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-result={outcome.variant}
      className={`${card} p-space-lg relative overflow-hidden`}
    >
      <div aria-hidden="true" className={`absolute top-0 left-0 bottom-0 w-2 ${STRIPE[outcome.variant]}`} />
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-space-md pl-space-sm">
        <div className="flex items-center gap-space-md min-w-0">
          {ok ? (
            <div className="w-16 h-16 rounded-full bg-secondary-container flex items-center justify-center text-on-secondary-container shadow-sm shrink-0">
              <Icon name="check_circle" filled className="text-[36px]" />
            </div>
          ) : (
            <div
              className={`w-12 h-12 rounded-full flex items-center justify-center shrink-0 ${
                outcome.variant === "error" ? "bg-error-container text-on-error-container" : "bg-tertiary-fixed text-on-tertiary-fixed"
              }`}
            >
              <Icon name={outcome.variant === "error" ? "warning" : "cancel"} className="text-[28px]" />
            </div>
          )}
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-space-xs flex-wrap">
              <span className={`${ok ? "font-headline-lg text-headline-lg text-on-surface" : `font-headline-sm text-headline-sm ${outcome.variant === "error" ? "text-error" : "text-on-tertiary-fixed-variant"}`} font-bold`}>
                {ok ? "Welcome!" : outcome.title}
              </span>
              <Pill tone={ok ? "ok" : outcome.variant === "error" ? "error" : "warn"} dot={ok}>
                {ok ? "Verified" : outcome.chip}
              </Pill>
            </div>
            <p className="font-body-md text-body-md text-on-surface-variant font-medium break-all">
              {ok ? `${outcome.result.email} · checked in at ${formatTimeSeconds(outcome.result.checked_in_at)}` : outcome.detail}
            </p>
            <p className="font-code-tabular text-body-sm text-outline mt-0.5 uppercase">Code {outcome.code}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function Recent({ rows, error }: { rows: AdminRegistration[] | null; error: unknown }) {
  const latest = (rows ?? [])
    .filter((r) => r.checked_in_at)
    .sort((a, b) => (b.checked_in_at ?? "").localeCompare(a.checked_in_at ?? ""))
    .slice(0, 10);
  return (
    <section className={`${card} p-space-lg flex flex-col gap-space-md`} aria-labelledby="recent-heading">
      <div className="flex items-center gap-space-xs flex-wrap">
        <h2 id="recent-heading" className="font-headline-sm text-headline-sm text-on-surface font-bold">Recent check-ins</h2>
        <Pill tone="primary">Live</Pill>
        {rows && <span className="font-body-sm text-body-sm text-on-surface-variant">last {Math.min(10, latest.length)}</span>}
      </div>
      {error !== null ? (
        <ErrorBox>{messageFor(error)}</ErrorBox>
      ) : !rows ? (
        <Loading what="Loading check-ins" />
      ) : latest.length === 0 ? (
        <p className="font-body-md text-body-md text-on-surface-variant py-space-md">No check-ins yet. They appear here as people arrive.</p>
      ) : (
        <div className="overflow-x-auto w-full">
          <table aria-label="Recent check-ins" className="w-full min-w-[30rem] text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase">
                <th scope="col" className="py-2.5 px-space-md rounded-l-lg">Time</th>
                <th scope="col" className="py-2.5 px-space-md">Attendee</th>
                <th scope="col" className="py-2.5 px-space-md rounded-r-lg">Code</th>
              </tr>
            </thead>
            <tbody className="font-body-md text-body-md text-on-surface">
              {latest.map((r) => (
                <tr key={r.id} className="hover:bg-surface-container-low/60 transition-colors">
                  <td className="py-3 px-space-md font-code-tabular text-body-sm text-on-surface-variant whitespace-nowrap tabular-nums">
                    {r.checked_in_at ? formatTimeSeconds(r.checked_in_at) : ""}
                  </td>
                  <td className="py-3 px-space-md font-semibold">
                    <span className="flex items-center gap-2 break-words">
                      <span aria-hidden="true" className="w-2 h-2 rounded-full bg-secondary shrink-0" />
                      {r.email}
                    </span>
                  </td>
                  <td className="py-3 px-space-md font-code-tabular text-body-sm whitespace-nowrap">{r.ticket_code}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Door screen: type (or scan) the code, Enter, see a big answer, next person. */
export function CheckIn() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [rows, setRows] = useState<AdminRegistration[] | null>(null);
  const [rowsError, setRowsError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);
  const live = useEventStream<Stats>(streams.stats(eventId), "stats");

  useEffect(() => {
    api.getEvent(eventId).then(setEvent, setLoadError);
  }, [eventId]);

  const loadRecent = useCallback(
    () =>
      api.registrations(eventId, "checked_in").then(
        (r) => {
          setRows(r);
          setRowsError(null);
        },
        setRowsError,
      ),
    [eventId],
  );
  // refreshed on every live frame (someone else's scan) and after our own successful scan
  useEffect(() => {
    void loadRecent();
  }, [loadRecent, live.data]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    const submitted = code.trim();
    setBusy(true);
    try {
      const result = await api.checkIn(eventId, code);
      setOutcome({ variant: "success", result, code: submitted });
      setCode(""); // ready for the next person
      void loadRecent();
    } catch (err) {
      setOutcome(describeError(err, submitted));
      input.current?.select(); // easy to correct a typo
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") setCode("");
  }

  if (loadError) return <div className={adminContainer}><ErrorBox>{messageFor(loadError)}</ErrorBox></div>;
  if (!event) return <div className={adminContainer}><Loading what="Loading event" /></div>;

  const s = live.data;
  const arrivedPct = s ? percent(s.checked_in, s.registered) : 0;

  return (
    <section className={`${adminContainer} flex flex-col gap-space-lg`}>
      <div className={`${card} p-space-md flex flex-col lg:flex-row items-start lg:items-center justify-between gap-space-md`}>
        <div className="flex items-center gap-space-md min-w-0">
          <div className="w-12 h-12 rounded-lg bg-primary-fixed flex items-center justify-center text-primary shrink-0">
            <Icon name="sensors" filled className="text-[28px]" />
          </div>
          <div className="min-w-0">
            <h1 className="font-headline-md text-headline-md text-on-surface break-words">Check-in: {event.title}</h1>
            <p className="font-body-sm text-body-sm text-on-surface-variant">
              {formatDateLong(event.starts_at)} · {formatTimeZoned(event.starts_at)} ·{" "}
              <Link to={`/admin/events/${eventId}`} className="text-primary hover:underline">Dashboard</Link>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-space-md w-full lg:w-auto lg:justify-end">
          <div className="flex items-center gap-space-md bg-surface-container-low px-space-md py-2 rounded-lg">
            <div className="flex flex-col">
              <span className={labelSm}>Live check-in quota</span>
              {s ? (
                <div className="flex items-baseline gap-space-xs">
                  <strong aria-label="Arrived" className="font-headline-sm text-headline-sm text-on-surface font-bold tabular-nums">
                    {s.checked_in} / {s.registered}
                    <span className="sr-only"> arrived</span>
                  </strong>
                  <span className="font-body-sm text-body-sm text-primary font-semibold tabular-nums">({formatPercent(arrivedPct)})</span>
                </div>
              ) : (
                <span className="font-body-sm text-body-sm text-on-surface-variant">counting…</span>
              )}
            </div>
            <div className="w-24 bg-surface-container-highest h-2.5 rounded-full overflow-hidden shrink-0">
              <div className="bg-primary h-full rounded-full transition-all duration-500" style={{ width: `${arrivedPct}%` }} />
            </div>
          </div>
          <LiveBadge status={live.status} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg">
        <div className="lg:col-span-8 flex flex-col gap-space-md">
          <div className={`${card} p-space-lg flex flex-col gap-space-md`}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-space-xs font-label-lg text-label-lg text-on-surface">
                <Icon name="qr_code_scanner" className="text-primary text-[20px]" />
                <label htmlFor="code">Ticket code</label>
              </div>
              <span className="flex items-center gap-space-xs font-label-sm text-label-sm text-on-surface-variant">
                Ready <span aria-hidden="true" className="w-2 h-2 rounded-full bg-secondary" />
              </span>
            </div>
            <form onSubmit={onSubmit} aria-label="Check in" className="flex flex-col sm:flex-row items-stretch gap-space-sm">
              <div className="relative flex-1">
                <Icon name="keyboard" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-outline text-[22px]" />
                <input
                  id="code"
                  ref={input}
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="ABCD-EFGH"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  onKeyDown={onKeyDown}
                  className="w-full pl-12 pr-24 py-3 rounded-lg bg-surface-container-lowest border border-outline-variant text-on-surface font-code-tabular text-body-lg uppercase tracking-wider placeholder:normal-case placeholder:tracking-normal placeholder:text-outline focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary shadow-sm"
                />
                <span aria-hidden="true" className="hidden md:block absolute right-3 top-1/2 -translate-y-1/2 font-label-sm text-label-sm text-outline uppercase">Esc to clear</span>
              </div>
              <button type="submit" disabled={busy} className={`${btnPrimary} !px-space-lg !py-3 shrink-0`}>
                <Icon name="verified" className="text-[20px]" />
                {busy ? "Checking…" : "Verify & Check-In"}
              </button>
            </form>
          </div>

          {outcome ? (
            <ResultCard outcome={outcome} />
          ) : (
            <div className="rounded-xl border-2 border-dashed border-outline-variant p-space-lg flex items-center gap-space-md text-on-surface-variant">
              <Icon name="qr_code_scanner" className="text-outline text-[32px]" />
              <p className="font-body-md text-body-md">Waiting for a ticket. Type or scan a code and press Enter.</p>
            </div>
          )}
        </div>

        <div className="lg:col-span-4 flex flex-col gap-space-md">
          <div className={`${card} p-space-md flex flex-col gap-space-sm`}>
            <div className="flex items-center justify-between">
              <h2 className="font-label-lg text-label-lg text-on-surface">Attendance</h2>
              <Pill tone="neutral">Live numbers</Pill>
            </div>
            {s ? (
              <div className="grid grid-cols-2 gap-space-sm pt-space-xs">
                {(
                  [
                    ["Registered", s.registered, "text-on-surface"],
                    ["Not arrived yet", s.confirmed, "text-on-surface"],
                    ["Waitlisted", s.waitlisted, "text-tertiary"],
                    ["Free seats", s.seats_left, "text-on-surface"],
                  ] as const
                ).map(([name, value, color]) => (
                  <div key={name} className="bg-surface-container-low p-space-sm rounded-lg flex flex-col">
                    <span className="font-label-sm text-label-sm text-on-surface-variant">{name}</span>
                    <span className={`font-headline-sm text-headline-sm font-bold tabular-nums ${color}`}>{value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <Loading what="Loading attendance" />
            )}
          </div>
        </div>
      </div>

      <Recent rows={rows} error={rowsError} />
    </section>
  );
}
