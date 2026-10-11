import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import {
  api,
  streams,
  type AdminRegistration,
  type PublicEvent,
  type RegistrationStatus,
  type Stats,
} from "../../api";
import { ErrorBox, LiveBadge, Loading, Notice, Stat } from "../../components/ui";
import { messageFor } from "../../errors";
import { formatDateTime, fromLocalInput, plural, toLocalInput } from "../../format";
import { useEventStream } from "../../useEventStream";

const TABS: { label: string; status?: RegistrationStatus }[] = [
  { label: "All" },
  { label: "Confirmed", status: "confirmed" },
  { label: "Checked in", status: "checked_in" },
  { label: "Waitlisted", status: "waitlisted" },
  { label: "Cancelled", status: "cancelled" },
];

function Counters({ stats }: { stats: Stats }) {
  return (
    <div className="stats" aria-label="Live counters">
      <Stat label="Registered" value={stats.registered} hint={`of ${stats.capacity} seats`} />
      <Stat label="Checked in" value={stats.checked_in} hint="arrived" />
      <Stat label="Not arrived yet" value={stats.confirmed} />
      <Stat label="Waitlisted" value={stats.waitlisted} />
      <Stat label="Free seats" value={stats.seats_left} />
      <Stat label="Cancelled" value={stats.cancelled} />
    </div>
  );
}

function Participants({ eventId, refreshKey }: { eventId: string; refreshKey: unknown }) {
  const [tab, setTab] = useState(0);
  const [rows, setRows] = useState<AdminRegistration[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const status = TABS[tab]?.status;

  useEffect(() => {
    api.registrations(eventId, status).then(setRows, setError);
  }, [eventId, status, refreshKey]);

  return (
    <section>
      <h2>Participants</h2>
      <div role="tablist" className="tabs">
        {TABS.map((t, i) => (
          <button key={t.label} role="tab" type="button" aria-selected={i === tab} onClick={() => setTab(i)}>
            {t.label}
          </button>
        ))}
      </div>
      {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
      {!rows && error === null && <Loading what="Loading participants" />}
      {rows && rows.length === 0 && <p className="muted">Nobody here.</p>}
      {rows && rows.length > 0 && (
        <table aria-label="Participants">
          <thead>
            <tr><th>Email</th><th>Status</th><th>Ticket</th><th>Registered</th><th>Checked in</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.email}</td>
                <td>{r.status === "waitlisted" ? `waitlisted #${r.waitlist_position}` : r.status.replace("_", " ")}</td>
                <td><code>{r.ticket_code}</code></td>
                <td>{formatDateTime(r.created_at)}</td>
                <td>{r.checked_in_at ? formatDateTime(r.checked_in_at) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function EditForm({ event, onSaved }: { event: PublicEvent; onSaved: (e: PublicEvent) => void }) {
  const [title, setTitle] = useState(event.title);
  const [description, setDescription] = useState(event.description);
  const [capacity, setCapacity] = useState(String(event.capacity));
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    setError(null);
    try {
      const saved = await api.updateEvent(event.id, { title, description, capacity: Number(capacity) });
      onSaved(saved);
      setMsg(saved.promoted_count ? `Saved. ${plural(saved.promoted_count, "person", "people")} moved from the waitlist.` : "Saved.");
    } catch (err) {
      setError(err);
    }
  }

  return (
    <form className="stack card" onSubmit={onSubmit} aria-label="Edit event">
      <h2>Edit</h2>
      <label htmlFor="edit-title">Title</label>
      <input id="edit-title" required value={title} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="edit-description">Description</label>
      <textarea id="edit-description" value={description} onChange={(e) => setDescription(e.target.value)} />
      <label htmlFor="edit-capacity">Seat limit</label>
      <input id="edit-capacity" type="number" min={1} required value={capacity} onChange={(e) => setCapacity(e.target.value)} />
      <button type="submit">Save</button>
      {msg && <Notice kind="ok">{msg}</Notice>}
      {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
    </form>
  );
}

function RescheduleForm({ event, onSaved }: { event: PublicEvent; onSaved: (e: PublicEvent) => void }) {
  const [value, setValue] = useState(toLocalInput(event.starts_at));
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    setError(null);
    try {
      const r = await api.reschedule(event.id, fromLocalInput(value));
      onSaved(r.event);
      setMsg(r.changed ? `Moved to ${formatDateTime(r.event.starts_at)}. ${plural(r.notified, "participant")} notified by email.` : "Same date: nothing changed.");
    } catch (err) {
      setError(err);
    }
  }

  return (
    <form className="stack card" onSubmit={onSubmit} aria-label="Reschedule">
      <h2>Reschedule</h2>
      <label htmlFor="new-date">New date and time (your local time)</label>
      <input id="new-date" type="datetime-local" required value={value} onChange={(e) => setValue(e.target.value)} />
      <button type="submit">Reschedule and notify everyone</button>
      {msg && <Notice kind="ok">{msg}</Notice>}
      {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
    </form>
  );
}

export function AdminDashboard() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [cancelMsg, setCancelMsg] = useState<string | null>(null);
  const live = useEventStream<Stats>(streams.stats(eventId), "stats");

  const loadEvent = useCallback(() => api.getEvent(eventId).then(setEvent, setError), [eventId]);
  useEffect(() => {
    loadEvent();
    api.stats(eventId).then(setStats, setError);
  }, [eventId, loadEvent]);

  if (error) return <ErrorBox>{messageFor(error)}</ErrorBox>;
  if (!event) return <Loading what="Loading event" />;
  const current = live.data ?? stats;

  async function onCancelEvent() {
    if (!window.confirm("Cancel this event? Everyone registered or waiting will be emailed.")) return;
    try {
      const r = await api.cancelEvent(eventId);
      setEvent(r.event);
      setCancelMsg(`Event cancelled. ${plural(r.notified, "participant")} notified.`);
    } catch (err) {
      setCancelMsg(messageFor(err));
    }
  }

  return (
    <article>
      <p><Link to="/admin">← All events</Link></p>
      <h1>{event.title}</h1>
      <p className="muted">
        {formatDateTime(event.starts_at)} · {event.status} · <Link to={`/events/${event.id}`}>public page</Link>
      </p>
      {event.status === "cancelled" && <Notice kind="warn">This event is cancelled.</Notice>}
      {live.status === "expired" && (
        <ErrorBox>Your login expired. <Link to={`/admin/login?next=/admin/events/${eventId}`}>Log in again</Link> for live updates.</ErrorBox>
      )}

      <p>
        <Link className="button" to={`/admin/events/${eventId}/checkin`}>Open check-in screen</Link>{" "}
        <LiveBadge status={live.status} />
      </p>
      {current ? <Counters stats={current} /> : <Loading what="Loading counters" />}
      {current && current.emails.failed > 0 && (
        <Notice kind="warn">{plural(current.emails.failed, "email")} could not be delivered.</Notice>
      )}

      <Participants eventId={eventId} refreshKey={live.data} />

      {event.status === "scheduled" && (
        <div className="grid">
          <EditForm key={`edit-${event.id}`} event={event} onSaved={setEvent} />
          <RescheduleForm key={`resched-${event.id}`} event={event} onSaved={setEvent} />
          <section className="card stack">
            <h2>Cancel event</h2>
            <button type="button" className="danger" onClick={onCancelEvent}>Cancel event and notify everyone</button>
          </section>
        </div>
      )}
      {cancelMsg && <Notice>{cancelMsg}</Notice>}
    </article>
  );
}
