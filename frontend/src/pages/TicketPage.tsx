import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type MyRegistration, type RegistrationStatus } from "../api";
import { Icon } from "../components/Icon";
import { btnDanger, btnSecondary, card, labelSm, pageContainer, pageX } from "../components/styles";
import { ErrorBox, Loading, Notice, Pill, type Tone } from "../components/ui";
import { messageFor } from "../errors";
import { countdown, formatDateLong, formatDateTime, formatTimeZoned, initialsOf } from "../format";
import { useNow } from "../useNow";

type Banner = { box: string; icon: string; text: string; pulse?: boolean };

function bannerFor(reg: MyRegistration): Banner {
  if (reg.event.status === "cancelled") {
    return { box: "bg-error text-on-error", icon: "event_busy", text: "This event has been cancelled by the organizer." };
  }
  switch (reg.status) {
    case "confirmed":
      return { box: "bg-secondary text-on-secondary", icon: "check_circle", text: "You're in! Your registration is confirmed.", pulse: true };
    case "checked_in":
      return {
        box: "bg-secondary text-on-secondary",
        icon: "how_to_reg",
        text: `You're all set. Entry recorded${reg.checked_in_at ? ` at ${formatDateTime(reg.checked_in_at)}` : ""}.`,
      };
    case "waitlisted":
      return { box: "bg-tertiary text-on-tertiary", icon: "hourglass_top", text: `You're #${reg.waitlist_position} on the waitlist.` };
    case "cancelled":
      return { box: "bg-inverse-surface text-inverse-on-surface", icon: "cancel", text: "This registration is cancelled." };
  }
}

const STATUS_CHIP: Record<RegistrationStatus, { tone: Tone; text: string }> = {
  confirmed: { tone: "ok", text: "Confirmed & valid" },
  checked_in: { tone: "primary", text: "Checked in" },
  waitlisted: { tone: "warn", text: "Waitlisted" },
  cancelled: { tone: "neutral", text: "Cancelled" },
};

function CountdownCard({ startsAt, cancelled }: { startsAt: string; cancelled: boolean }) {
  const now = useNow(15_000);
  const c = countdown(startsAt, now);
  return (
    <div className={`${card} p-space-lg flex flex-col gap-space-md`}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-headline-sm text-headline-sm text-on-surface">Event countdown</h2>
        <span className="font-label-sm text-label-sm text-secondary font-bold uppercase">
          {cancelled ? "Cancelled" : c.started ? "Started" : "Starts soon"}
        </span>
      </div>
      {cancelled || c.started ? (
        <p className="font-body-md text-body-md text-on-surface-variant">
          {cancelled ? "This event will not take place." : "The event has started."}
        </p>
      ) : (
        <div role="timer" aria-label="Time until the event starts" className="grid grid-cols-3 gap-space-sm text-center">
          {(
            [
              ["Days", c.days],
              ["Hours", c.hours],
              ["Minutes", c.minutes],
            ] as const
          ).map(([name, value]) => (
            <div key={name} className="bg-surface-container-low p-space-sm rounded-lg">
              <span className="font-display-hero text-headline-md text-primary font-bold block tabular-nums">{value}</span>
              <span className="font-label-sm text-label-sm text-on-surface-variant uppercase">{name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** /r/:token: the link from every email. Shows the ticket and lets the holder cancel. */
export function TicketPage() {
  const { token = "" } = useParams();
  const [reg, setReg] = useState<MyRegistration | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => api.getRegistration(token).then(setReg, setLoadError), [token]);
  useEffect(() => {
    load();
  }, [load]);

  if (loadError) return <div className={`${pageContainer} py-space-xl`}><ErrorBox>{messageFor(loadError)}</ErrorBox></div>;
  if (!reg) return <div className={pageContainer}><Loading what="Loading your ticket" /></div>;

  const { event } = reg;
  const banner = bannerFor(reg);
  const chip = STATUS_CHIP[reg.status];
  const started = new Date(event.starts_at) <= new Date();
  const eventCancelled = event.status === "cancelled";
  const canCancel = (reg.status === "confirmed" || reg.status === "waitlisted") && !eventCancelled && !started;
  const hasTicket = reg.ticket_code !== null && (reg.status === "confirmed" || reg.status === "checked_in");

  async function onCancel() {
    const what = reg?.status === "waitlisted" ? "leave the waitlist" : "give up your seat";
    if (!window.confirm(`Really ${what}? This can't be undone.`)) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelRegistration(token);
      await load();
    } catch (err) {
      setCancelError(err);
    } finally {
      setCancelling(false);
    }
  }

  async function copyCode() {
    if (!reg?.ticket_code) return;
    try {
      await navigator.clipboard.writeText(reg.ticket_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable (insecure context): the code is on screen anyway */
    }
  }

  return (
    <article className="flex flex-col w-full">
      <div className={`w-full ${banner.box} ${pageX} py-space-sm flex flex-col sm:flex-row items-center justify-between gap-space-sm shadow-sm`}>
        <div className="flex items-center gap-space-sm">
          {banner.pulse ? (
            <span aria-hidden="true" className="flex h-2.5 w-2.5 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary-fixed opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-secondary-fixed" />
            </span>
          ) : (
            <Icon name={banner.icon} filled className="text-[20px]" />
          )}
          <p className="font-label-lg text-label-lg tracking-tight">{banner.text}</p>
        </div>
        <p className="font-body-sm text-body-sm opacity-80 break-all text-center sm:text-right">
          Registered with <span className="font-semibold">{reg.email}</span>
        </p>
      </div>

      <div className={`w-full max-w-7xl mx-auto ${pageX} py-space-xl flex flex-col gap-space-xl`}>
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md">
          <div className="min-w-0">
            <h1 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface break-words">
              {event.title}
            </h1>
            <p className="font-body-md text-body-md text-on-surface-variant mt-1">
              {formatDateLong(event.starts_at)} · {formatTimeZoned(event.starts_at)}
            </p>
          </div>
          <Pill tone={chip.tone} dot className="self-start md:self-auto !px-3 !py-1.5">{chip.text}</Pill>
        </div>

        <div className="w-full flex flex-col xl:flex-row items-stretch gap-space-xl">
          <div className="w-full xl:w-7/12 flex flex-col">
            <div className="relative bg-surface-container-lowest rounded-xl shadow-xl overflow-hidden flex flex-col md:flex-row">
              <div className="p-space-lg md:p-space-xl flex-1 flex flex-col gap-space-lg bg-surface-container-lowest relative z-10 min-w-0">
                <div className="flex items-center gap-space-xs">
                  <div aria-hidden="true" className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-on-primary font-headline-sm text-headline-sm shrink-0">
                    {initialsOf(event.title)}
                  </div>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface leading-tight break-words min-w-0">{event.title}</h2>
                </div>
                <div className="flex flex-col gap-space-xs">
                  <span className={labelSm}>Attendee</span>
                  <span aria-label="Attendee" className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight break-all">
                    {reg.email}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-space-md">
                  <div className="flex flex-col">
                    <span className={labelSm}>Event date</span>
                    <span className="font-label-lg text-label-lg text-on-surface font-semibold">{formatDateLong(event.starts_at)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className={labelSm}>Starts</span>
                    <span className="font-label-lg text-label-lg text-on-surface font-semibold">{formatTimeZoned(event.starts_at)}</span>
                  </div>
                </div>
              </div>

              <div className="relative w-full md:w-64 bg-surface-container-low p-space-lg flex flex-col items-center justify-center gap-space-sm text-center">
                <div aria-hidden="true" className="hidden md:flex absolute -left-3 top-0 bottom-0 w-6 flex-col justify-between py-2 pointer-events-none z-20">
                  <div className="w-6 h-6 rounded-full bg-surface" />
                  <div className="w-6 h-6 rounded-full bg-surface" />
                </div>
                <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-widest">Ticket code</span>
                {hasTicket ? (
                  <>
                    <div className="p-3 bg-surface-container-lowest rounded-xl shadow-md w-full">
                      <span aria-label="Ticket code" className="font-code-tabular text-[22px] leading-8 text-primary font-bold tracking-wider tabular-nums whitespace-nowrap">
                        {reg.ticket_code}
                      </span>
                    </div>
                    <p className="font-body-sm text-body-sm text-on-surface-variant">Show this code at the entrance.</p>
                    <button type="button" onClick={copyCode} className={`${btnSecondary} !py-1.5 !text-label-md`}>
                      <Icon name={copied ? "check" : "content_copy"} className="text-[16px]" />
                      {copied ? "Copied" : "Copy code"}
                    </button>
                  </>
                ) : (
                  <div className="p-3 bg-surface-container-lowest rounded-xl shadow-sm w-full">
                    <Icon name="confirmation_number" className="text-outline text-[32px]" />
                    <p className="font-body-sm text-body-sm text-on-surface-variant mt-1">
                      {reg.status === "waitlisted" ? "No ticket yet. You get one automatically if a seat frees up." : "No valid ticket."}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="w-full xl:w-5/12 flex flex-col gap-space-md">
            <CountdownCard startsAt={event.starts_at} cancelled={eventCancelled} />

            <div className={`${card} p-space-lg flex flex-col gap-space-sm`}>
              <h2 className="font-headline-sm text-headline-sm text-on-surface">Manage registration</h2>
              {canCancel ? (
                <>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    You can cancel until the event starts. {reg.status === "confirmed" ? "Your seat goes to the next person in line." : "You'll leave the queue and nobody's place changes."}
                  </p>
                  <button type="button" className={btnDanger} onClick={onCancel} disabled={cancelling}>
                    <Icon name="person_cancel" className="text-[18px]" />
                    {cancelling ? "Cancelling…" : reg.status === "waitlisted" ? "Leave the waitlist" : "Cancel my registration"}
                  </button>
                </>
              ) : reg.status === "cancelled" ? (
                <Notice>
                  Changed your mind? <Link to={`/events/${event.id}`} className="text-primary font-semibold hover:underline">Register again</Link> while registration is open.
                </Notice>
              ) : (
                <p className="font-body-sm text-body-sm text-on-surface-variant">
                  {reg.status === "checked_in"
                    ? "Checked-in tickets can't be cancelled."
                    : eventCancelled
                      ? "Nothing to cancel: the event was cancelled."
                      : "Registration can no longer be changed because the event has started."}
                </p>
              )}
              {cancelError !== null && <ErrorBox>{messageFor(cancelError)}</ErrorBox>}
              <Link to={`/events/${event.id}`} className="font-label-md text-label-md text-primary hover:underline inline-flex items-center gap-1 mt-1">
                Event page <Icon name="north_east" className="text-[16px]" />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}
