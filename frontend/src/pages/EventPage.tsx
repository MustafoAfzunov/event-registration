import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { api, streams, type Availability, type PublicEvent, type RegisterResult } from "../api";
import { Icon } from "../components/Icon";
import { btnPrimary, btnWarn, card, input, label, labelSm, pageContainer, pageX } from "../components/styles";
import { ErrorBox, LiveBadge, Loading, Notice, Pill } from "../components/ui";
import { errorCode, messageFor } from "../errors";
import { capacityTier, formatDateLong, formatPercent, formatTimeZoned, percent, plural, type CapacityTier } from "../format";
import { useEventStream } from "../useEventStream";
import { useNow } from "../useNow";

function RegisterOutcome({ result }: { result: RegisterResult }) {
  if (!result.created) {
    return (
      <Notice kind="info">
        <strong>You're already registered</strong> with {result.email}
        {result.status === "waitlisted"
          ? ` and you're #${result.waitlist_position} on the waitlist.`
          : ` (${result.status.replace("_", " ")}).`}{" "}
        No second seat was taken. Your ticket is in the email we sent earlier.
      </Notice>
    );
  }
  if (result.status === "confirmed") {
    return (
      <Notice kind="ok">
        <strong>You're in!</strong> Your ticket is on its way to {result.email}.
      </Notice>
    );
  }
  return (
    <Notice kind="warn">
      <strong>The event is full.</strong> You're #{result.waitlist_position} on the waitlist. If a seat
      frees up it goes to the first person in line automatically, and we'll email {result.email}.
    </Notice>
  );
}

// Availability box variants (DESIGN.md: emerald = available, rose = high demand, amber = waitlist).
const TIER: Record<CapacityTier, { box: string; icon: string; iconColor: string; label: string; labelColor: string; bar: string }> = {
  available: { box: "bg-secondary-fixed/30", icon: "event_available", iconColor: "text-secondary", label: "Seats available", labelColor: "text-on-secondary-fixed-variant", bar: "bg-secondary" },
  high: { box: "bg-error-container/60", icon: "timer", iconColor: "text-error", label: "High demand", labelColor: "text-on-error-container", bar: "bg-error" },
  full: { box: "bg-tertiary-fixed/40", icon: "hourglass_top", iconColor: "text-tertiary", label: "Sold out · waitlist open", labelColor: "text-on-tertiary-fixed-variant", bar: "bg-tertiary" },
};

function AvailabilityBox({ view, status }: { view: PublicEvent; status: Parameters<typeof LiveBadge>[0]["status"] }) {
  const cancelled = view.status === "cancelled";
  const tier = capacityTier(view.capacity, view.seats_left);
  const t = TIER[tier];
  const taken = view.capacity - view.seats_left;
  const pct = percent(taken, view.capacity);
  return (
    <div className={`p-3 rounded-lg flex items-start gap-3 mb-space-md ${cancelled ? "bg-surface-container" : t.box}`} aria-live="polite">
      <Icon name={cancelled ? "event_busy" : t.icon} className={`${cancelled ? "text-outline" : t.iconColor} text-[22px] mt-0.5`} />
      <div className="flex-grow min-w-0">
        {!cancelled && <span className={`font-label-sm text-label-sm uppercase font-bold ${t.labelColor}`}>{t.label}</span>}
        <p className="font-code-tabular text-code-tabular font-bold text-on-surface tabular-nums">
          {cancelled ? (
            "This event has been cancelled."
          ) : view.seats_left > 0 ? (
            <>{plural(view.seats_left, "seat")} left</>
          ) : (
            <>Full · {plural(view.waitlist_count, "person", "people")} on the waitlist</>
          )}
        </p>
        {!cancelled && (
          <>
            <div className="w-full bg-surface-container-highest h-2 rounded-full overflow-hidden mt-1.5">
              <div className={`${t.bar} h-full rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
            </div>
            <div className="flex justify-between items-center gap-2 text-[11px] text-on-surface-variant mt-1 font-medium tabular-nums">
              <span>{taken} / {view.capacity} registered</span>
              <span>{formatPercent(pct)} full</span>
            </div>
          </>
        )}
        <div className="mt-2"><LiveBadge status={status} /></div>
      </div>
    </div>
  );
}

function InfoTile({ icon, caption, title, detail }: { icon: string; caption: string; title: string; detail: string }) {
  return (
    <div className="flex items-start gap-space-sm min-w-0">
      <div className="w-12 h-12 rounded-xl bg-surface-container flex items-center justify-center text-primary shrink-0">
        <Icon name={icon} className="text-[26px]" />
      </div>
      <div className="min-w-0">
        <p className={labelSm}>{caption}</p>
        <p className="font-headline-sm text-headline-sm text-on-surface mt-0.5">{title}</p>
        <p className="font-body-md text-body-md text-on-surface-variant">{detail}</p>
      </div>
    </div>
  );
}

export function EventPage() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const live = useEventStream<Availability>(event ? streams.availability(eventId) : null, "availability");
  const now = useNow(30_000);

  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<RegisterResult | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);

  useEffect(() => {
    api.getEvent(eventId).then(setEvent, setLoadError);
  }, [eventId]);

  if (loadError) {
    return <div className={`${pageContainer} py-space-xl`}><ErrorBox>{messageFor(loadError)}</ErrorBox></div>;
  }
  if (!event) {
    return <div className={pageContainer}><Loading what="Loading event" /></div>;
  }

  // Live numbers override the initial load as soon as the stream sends them.
  const view = live.data ? { ...event, ...live.data } : event;
  const started = new Date(view.starts_at).getTime() <= now;
  const open = view.status === "scheduled" && !started;
  const full = view.seats_left <= 0;
  const taken = view.capacity - view.seats_left;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setResult(null);
    try {
      setResult(await api.register(eventId, email));
    } catch (err) {
      setSubmitError(err);
      if (errorCode(err) === "registration_closed" || errorCode(err) === "event_cancelled") {
        api.getEvent(eventId).then(setEvent, () => undefined);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className="flex flex-col w-full">
      <section className="relative w-full overflow-hidden bg-surface-container-high pb-space-xl">
        <div aria-hidden="true" className="absolute -top-32 -left-20 w-96 h-96 rounded-full bg-primary/10 blur-3xl pointer-events-none" />
        <div aria-hidden="true" className="absolute top-1/2 -right-24 w-80 h-80 rounded-full bg-secondary-container/40 blur-3xl pointer-events-none" />
        <div className={`relative w-full max-w-7xl mx-auto ${pageX} pt-space-lg`}>
          <div className="flex flex-wrap items-center gap-2 mb-space-md">
            {view.status === "cancelled" ? (
              <Pill tone="error" className="shadow-sm">Cancelled</Pill>
            ) : started ? (
              <Pill tone="neutral" className="shadow-sm">Started</Pill>
            ) : full ? (
              <Pill tone="warn" dot className="shadow-sm">Full · waitlist open</Pill>
            ) : (
              <Pill tone="ok" dot pulse className="shadow-sm">Registration open</Pill>
            )}
          </div>
          <h1 className="font-display-hero text-display-hero-mobile md:text-display-hero text-on-surface tracking-tight break-words max-w-4xl">
            {view.title}
          </h1>
        </div>
      </section>

      <div className={`w-full max-w-7xl mx-auto ${pageX} py-space-xl`}>
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">
          <div className="lg:col-span-8 flex flex-col gap-space-xl order-2 lg:order-1">
            <div className={`${card} p-space-lg`}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-space-lg">
                <InfoTile icon="calendar_today" caption="Date & Time" title={formatDateLong(view.starts_at)} detail={formatTimeZoned(view.starts_at)} />
                <InfoTile
                  icon="event_seat"
                  caption="Capacity"
                  title={plural(view.capacity, "seat")}
                  detail={`${taken} registered · ${view.waitlist_count} waiting`}
                />
              </div>
            </div>

            <section className="space-y-space-md">
              <h2 className="font-headline-md text-headline-md text-on-surface flex items-center gap-2">
                <Icon name="auto_stories" className="text-primary" />
                About this event
              </h2>
              <div className={`${card} p-space-lg font-body-lg text-body-lg text-on-surface-variant`}>
                {view.description ? (
                  <p className="whitespace-pre-wrap break-words">{view.description}</p>
                ) : (
                  <p className="text-outline">The organizer hasn't added a description yet.</p>
                )}
              </div>
            </section>
          </div>

          <div className="lg:col-span-4 lg:sticky lg:top-24 order-1 lg:order-2">
            <div className="bg-surface-container-lowest rounded-xl shadow-xl overflow-hidden p-space-md sm:p-space-lg">
              <AvailabilityBox view={view} status={live.status} />

              {open && full && (
                <div className="mb-space-md p-3 rounded-lg bg-tertiary-fixed/30 text-on-tertiary-fixed flex items-start gap-2">
                  <Icon name="hourglass_top" className="text-tertiary text-[20px] shrink-0" />
                  <div>
                    <p className="font-label-md text-label-md font-semibold">Join the waitlist</p>
                    <p className="font-body-sm text-body-sm mt-0.5">
                      All seats are taken. If one frees up, the first person in line gets it automatically and we
                      email them their ticket. You won't be charged or double-booked.
                    </p>
                  </div>
                </div>
              )}

              {open ? (
                <form className="space-y-3" onSubmit={onSubmit} aria-label="Register">
                  <div>
                    <label htmlFor="email" className={label}>Your email</label>
                    <div className="relative">
                      <Icon name="mail" className="absolute left-3 top-1/2 -translate-y-1/2 text-outline text-[18px]" />
                      <input
                        id="email"
                        type="email"
                        required
                        autoComplete="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="you@example.com"
                        className={`${input} pl-9`}
                      />
                    </div>
                  </div>
                  <button type="submit" disabled={submitting} className={`w-full ${full ? btnWarn : `${btnPrimary} !py-3`}`}>
                    <Icon name={full ? "hourglass_top" : "how_to_reg"} className="text-[20px]" />
                    {submitting ? "Registering…" : full ? "Join waitlist" : "Register"}
                  </button>
                </form>
              ) : (
                view.status === "scheduled" && <Notice>Registration is closed: the event has started.</Notice>
              )}

              {(submitError !== null || result) && (
                <div className="mt-space-md space-y-space-sm">
                  {submitError !== null && <ErrorBox>{messageFor(submitError)}</ErrorBox>}
                  {result && <RegisterOutcome result={result} />}
                </div>
              )}

              <div className="mt-space-md pt-3 border-t border-surface-container flex items-start gap-2 text-secondary font-label-sm text-label-sm">
                <Icon name="verified" className="text-[18px] shrink-0" />
                <span>Cancel anytime before the event starts, using the link in your confirmation email.</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}
