import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type PublicEvent } from "../api";
import { ErrorBox, Loading } from "../components/ui";
import { messageFor } from "../errors";
import { formatDateTime } from "../format";

export function EventsList() {
  const [events, setEvents] = useState<PublicEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.listEvents().then(setEvents, setError);
  }, []);

  if (error) return <ErrorBox>{messageFor(error)}</ErrorBox>;
  if (!events) return <Loading what="Loading events" />;
  return (
    <section>
      <h1>Upcoming events</h1>
      {events.length === 0 && <p className="muted">No upcoming events yet.</p>}
      <ul className="cards">
        {events.map((e) => (
          <li key={e.id} className="card">
            <Link to={`/events/${e.id}`}>
              <strong>{e.title}</strong>
            </Link>
            <div className="muted">{formatDateTime(e.starts_at)}</div>
            <div>{e.seats_left > 0 ? `${e.seats_left} seats left` : `Full · ${e.waitlist_count} waiting`}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
