import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { api, streams, type Availability, type PublicEvent, type RegisterResult } from "../api";
import { ErrorBox, LiveBadge, Loading, Notice } from "../components/ui";
import { errorCode, messageFor } from "../errors";
import { formatDateTime, plural } from "../format";
import { useEventStream } from "../useEventStream";

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

export function EventPage() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const live = useEventStream<Availability>(event ? streams.availability(eventId) : null, "availability");

  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<RegisterResult | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);

  useEffect(() => {
    api.getEvent(eventId).then(setEvent, setLoadError);
  }, [eventId]);

  if (loadError) return <ErrorBox>{messageFor(loadError)}</ErrorBox>;
  if (!event) return <Loading what="Loading event" />;

  // Live numbers override the initial load as soon as the stream sends them.
  const view = live.data ? { ...event, ...live.data } : event;
  const started = new Date(view.starts_at) <= new Date();
  const open = view.status === "scheduled" && !started;

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
    <article>
      <h1>{view.title}</h1>
      <p className="muted">{formatDateTime(view.starts_at)}</p>
      {view.description && <p className="description">{view.description}</p>}

      <div className="availability" aria-live="polite">
        {view.status === "cancelled" ? (
          <strong>This event has been cancelled.</strong>
        ) : view.seats_left > 0 ? (
          <strong>{plural(view.seats_left, "seat")} left</strong>
        ) : (
          <strong>Full · {plural(view.waitlist_count, "person", "people")} on the waitlist</strong>
        )}{" "}
        <span className="muted">of {view.capacity}</span> <LiveBadge status={live.status} />
      </div>

      {open ? (
        <form className="stack" onSubmit={onSubmit} aria-label="Register">
          <label htmlFor="email">Your email</label>
          <div className="row">
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
            <button type="submit" disabled={submitting}>
              {submitting ? "Registering…" : view.seats_left > 0 ? "Register" : "Join waitlist"}
            </button>
          </div>
        </form>
      ) : (
        view.status === "scheduled" && <Notice>Registration is closed: the event has started.</Notice>
      )}
      {submitError !== null && <ErrorBox>{messageFor(submitError)}</ErrorBox>}
      {result && <RegisterOutcome result={result} />}
      <p className="muted small">
        Need to cancel? Open the link in your confirmation email: it shows your ticket and lets you
        give your seat to the next person on the waitlist.
      </p>
    </article>
  );
}
