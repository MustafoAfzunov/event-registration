import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api, type PublicEvent } from "../../api";
import { ErrorBox, Loading } from "../../components/ui";
import { messageFor } from "../../errors";
import { formatDateTime, fromLocalInput } from "../../format";

function CreateEventForm() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [capacity, setCapacity] = useState("50");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createEvent({
        title,
        description,
        starts_at: fromLocalInput(startsAt),
        capacity: Number(capacity),
      });
      navigate(`/admin/events/${created.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form className="stack card" onSubmit={onSubmit} aria-label="Create event">
      <h2>New event</h2>
      <label htmlFor="title">Title</label>
      <input id="title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="description">Description</label>
      <textarea id="description" maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} />
      <label htmlFor="starts_at">Starts at (your local time)</label>
      <input id="starts_at" type="datetime-local" required value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
      <label htmlFor="capacity">Seat limit</label>
      <input id="capacity" type="number" min={1} max={100000} required value={capacity} onChange={(e) => setCapacity(e.target.value)} />
      <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create event"}</button>
      {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
    </form>
  );
}

export function AdminEvents() {
  const [events, setEvents] = useState<PublicEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.adminEvents().then(setEvents, setError);
  }, []);

  return (
    <section>
      <h1>Your events</h1>
      {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
      {!events && error === null && <Loading what="Loading events" />}
      {events && events.length === 0 && <p className="muted">No events yet. Create the first one below.</p>}
      {events && events.length > 0 && (
        <table>
          <thead>
            <tr><th>Event</th><th>Starts</th><th>Status</th><th>Seats left</th><th>Waitlist</th></tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td><Link to={`/admin/events/${e.id}`}>{e.title}</Link></td>
                <td>{formatDateTime(e.starts_at)}</td>
                <td>{e.status}</td>
                <td>{e.seats_left} / {e.capacity}</td>
                <td>{e.waitlist_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <CreateEventForm />
    </section>
  );
}
