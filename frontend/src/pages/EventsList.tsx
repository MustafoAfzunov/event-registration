import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type PublicEvent } from "../api";
import { Icon } from "../components/Icon";
import { card, pageContainer } from "../components/styles";
import { ErrorBox, Loading, Pill } from "../components/ui";
import { messageFor } from "../errors";
import { formatDateLong, formatTimeZoned, plural } from "../format";

export function EventsList() {
  const [events, setEvents] = useState<PublicEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.listEvents().then(setEvents, setError);
  }, []);

  return (
    <section className={`${pageContainer} py-space-xl`}>
      <h1 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface">Upcoming events</h1>
      <p className="font-body-lg text-body-lg text-on-surface-variant mt-1 mb-space-lg">Pick an event to see its details and register.</p>
      {error ? (
        <ErrorBox>{messageFor(error)}</ErrorBox>
      ) : !events ? (
        <Loading what="Loading events" />
      ) : events.length === 0 ? (
        <div className={`${card} p-space-xl text-center`}>
          <Icon name="event_busy" className="text-outline text-[40px]" />
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-2">No upcoming events yet.</p>
        </div>
      ) : (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">
          {events.map((e) => (
            <li key={e.id} className={`${card} relative p-space-lg hover:shadow-md transition-shadow flex flex-col gap-space-sm`}>
              <Link to={`/events/${e.id}`} className="font-headline-sm text-headline-sm text-on-surface hover:text-primary after:absolute after:inset-0 after:rounded-xl">
                {e.title}
              </Link>
              <p className="font-body-md text-body-md text-on-surface-variant flex items-center gap-1.5">
                <Icon name="calendar_today" className="text-[18px] text-primary" />
                {formatDateLong(e.starts_at)} · {formatTimeZoned(e.starts_at)}
              </p>
              <div className="mt-auto pt-space-xs">
                {e.seats_left > 0 ? (
                  <Pill tone="ok" dot>{plural(e.seats_left, "seat")} left</Pill>
                ) : (
                  <Pill tone="warn" dot>Full · {e.waitlist_count} waiting</Pill>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
