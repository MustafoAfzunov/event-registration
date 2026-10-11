import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type MyRegistration } from "../api";
import { ErrorBox, Loading, Notice } from "../components/ui";
import { messageFor } from "../errors";
import { formatDateTime } from "../format";

/** /r/:token: the link from every email. Shows the ticket and lets the holder cancel. */
export function TicketPage() {
  const { token = "" } = useParams();
  const [reg, setReg] = useState<MyRegistration | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<unknown>(null);

  const load = useCallback(() => api.getRegistration(token).then(setReg, setLoadError), [token]);
  useEffect(() => {
    load();
  }, [load]);

  if (loadError) return <ErrorBox>{messageFor(loadError)}</ErrorBox>;
  if (!reg) return <Loading what="Loading your ticket" />;

  const { event } = reg;
  const started = new Date(event.starts_at) <= new Date();
  const canCancel =
    (reg.status === "confirmed" || reg.status === "waitlisted") &&
    event.status === "scheduled" &&
    !started;

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

  return (
    <article>
      <h1>{event.title}</h1>
      <p className="muted">{formatDateTime(event.starts_at)}</p>
      {event.status === "cancelled" && <Notice kind="warn">This event has been cancelled by the organizer.</Notice>}
      <p>Registration for <strong>{reg.email}</strong></p>

      {reg.status === "confirmed" && reg.ticket_code && (
        <div className="ticket">
          <div className="muted">Your ticket code</div>
          <div className="ticket-code" aria-label="Ticket code">{reg.ticket_code}</div>
          <div className="muted">Show this code at the entrance.</div>
        </div>
      )}
      {reg.status === "checked_in" && (
        <Notice kind="ok">
          Checked in{reg.checked_in_at ? ` at ${formatDateTime(reg.checked_in_at)}` : ""}. Enjoy the event!
        </Notice>
      )}
      {reg.status === "waitlisted" && (
        <Notice kind="warn">
          You're <strong>#{reg.waitlist_position}</strong> on the waitlist. If a seat frees up you get it
          automatically and we'll email you your ticket.
        </Notice>
      )}
      {reg.status === "cancelled" && (
        <Notice>
          This registration is cancelled. <Link to={`/events/${event.id}`}>Register again</Link> if
          you changed your mind.
        </Notice>
      )}

      {canCancel && (
        <button type="button" className="danger" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Cancelling…" : reg.status === "waitlisted" ? "Leave the waitlist" : "Cancel my registration"}
        </button>
      )}
      {cancelError !== null && <ErrorBox>{messageFor(cancelError)}</ErrorBox>}
      <p><Link to={`/events/${event.id}`}>Event page</Link></p>
    </article>
  );
}
