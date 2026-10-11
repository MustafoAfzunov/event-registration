import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, streams, type CheckInResult, type PublicEvent, type Stats } from "../../api";
import { ErrorBox, LiveBadge, Loading } from "../../components/ui";
import { messageFor } from "../../errors";
import { formatTime } from "../../format";
import { useEventStream } from "../../useEventStream";

type Outcome = { ok: true; result: CheckInResult } | { ok: false; title: string; detail: string };

function describeError(err: unknown): Outcome {
  if (err instanceof ApiError) {
    const email = typeof err.details.email === "string" ? err.details.email : "";
    switch (err.code) {
      case "already_checked_in": {
        const at = typeof err.details.checked_in_at === "string" ? formatTime(err.details.checked_in_at) : "?";
        return { ok: false, title: "Already used", detail: `This ticket was checked in at ${at}${email ? ` (${email})` : ""}.` };
      }
      case "ticket_cancelled":
        return { ok: false, title: "Ticket cancelled", detail: `${email || "This person"} cancelled their registration.` };
      case "ticket_waitlisted":
        return { ok: false, title: "No seat (waitlist)", detail: `${email || "This person"} is on the waitlist.` };
      case "ticket_not_found":
        return { ok: false, title: "Unknown code", detail: "No ticket with this code for this event." };
      case "invalid_code_format":
        return { ok: false, title: "Not a ticket code", detail: "Codes have 8 letters/digits, e.g. ABCD-EFGH." };
    }
  }
  return { ok: false, title: "Check-in failed", detail: messageFor(err) };
}

/** Door screen: type (or scan) the code, Enter, see a big green/red answer, next person. */
export function CheckIn() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const live = useEventStream<Stats>(streams.stats(eventId), "stats");

  useEffect(() => {
    api.getEvent(eventId).then(setEvent, setLoadError);
  }, [eventId]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    try {
      const result = await api.checkIn(eventId, code);
      setOutcome({ ok: true, result });
      setCode(""); // ready for the next person
    } catch (err) {
      setOutcome(describeError(err));
      input.current?.select(); // easy to correct a typo
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }

  if (loadError) return <ErrorBox>{messageFor(loadError)}</ErrorBox>;
  if (!event) return <Loading what="Loading event" />;

  return (
    <section className="checkin">
      <p><Link to={`/admin/events/${eventId}`}>← Dashboard</Link></p>
      <h1>Check-in: {event.title}</h1>
      <p>
        {live.data ? (
          <strong aria-label="Arrived">{live.data.checked_in} / {live.data.registered} arrived</strong>
        ) : (
          <span className="muted">counting…</span>
        )}{" "}
        <LiveBadge status={live.status} />
      </p>
      <form onSubmit={onSubmit} className="row" aria-label="Check in">
        <label htmlFor="code" className="visually-hidden">Ticket code</label>
        <input
          id="code"
          ref={input}
          className="code-input"
          autoFocus
          autoComplete="off"
          spellCheck={false}
          placeholder="ABCD-EFGH"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <button type="submit" disabled={busy}>Check in</button>
      </form>
      {outcome && (
        <div className={`result ${outcome.ok ? "result-ok" : "result-error"}`} role="alert" aria-live="assertive">
          {outcome.ok ? (
            <>
              <div className="result-title">✓ Welcome!</div>
              <div>{outcome.result.email} · checked in at {formatTime(outcome.result.checked_in_at)}</div>
            </>
          ) : (
            <>
              <div className="result-title">✗ {outcome.title}</div>
              <div>{outcome.detail}</div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
