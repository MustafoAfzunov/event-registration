import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, type PublicEvent } from "../../api";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { adminContainer, btnPrimary, btnSecondary, card, input, label } from "../../components/styles";
import { ErrorBox, Loading, Pill, type Tone } from "../../components/ui";
import { messageFor } from "../../errors";
import { formatDateLong, formatTimeZoned, fromLocalInput } from "../../format";

function CreateEventModal({ onClose }: { onClose: () => void }) {
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
    <Modal
      title="Create event"
      subtitle="People can register as soon as it is saved."
      icon="add_circle"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" form="create-event-form" className={btnPrimary} disabled={busy}>
            <Icon name="check" className="text-[18px]" />
            {busy ? "Creating…" : "Create event"}
          </button>
        </>
      }
    >
      <form id="create-event-form" className="space-y-3" onSubmit={onSubmit} aria-label="Create event">
        <div>
          <label htmlFor="title" className={label}>Title</label>
          <input id="title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} className={input} />
        </div>
        <div>
          <label htmlFor="description" className={label}>Description</label>
          <textarea id="description" rows={3} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} className={input} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-md">
          <div>
            <label htmlFor="starts_at" className={label}>Starts at (your local time)</label>
            <input id="starts_at" type="datetime-local" required value={startsAt} onChange={(e) => setStartsAt(e.target.value)} className={input} />
          </div>
          <div>
            <label htmlFor="capacity" className={label}>Seat limit</label>
            <input id="capacity" type="number" min={1} max={100000} required value={capacity} onChange={(e) => setCapacity(e.target.value)} className={input} />
          </div>
        </div>
        {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
      </form>
    </Modal>
  );
}

function statusOf(e: PublicEvent): { tone: Tone; text: string } {
  if (e.status === "cancelled") return { tone: "error", text: "Cancelled" };
  if (new Date(e.starts_at) <= new Date()) return { tone: "neutral", text: "Started" };
  return e.seats_left > 0 ? { tone: "ok", text: "Registration open" } : { tone: "warn", text: "Full" };
}

export function AdminEvents() {
  const [events, setEvents] = useState<PublicEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [params, setParams] = useSearchParams();
  const creating = params.get("new") === "1";

  useEffect(() => {
    api.adminEvents().then(setEvents, setError);
  }, []);

  const setCreating = (open: boolean) => setParams(open ? { new: "1" } : {}, { replace: true });

  return (
    <section className={`${adminContainer} flex flex-col gap-space-lg`}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-md">
        <div>
          <h1 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface">Your events</h1>
          <p className="font-body-md text-body-md text-on-surface-variant">Every event, past and upcoming. Open one for live counters and the check-in terminal.</p>
        </div>
        <button type="button" className={btnPrimary} onClick={() => setCreating(true)}>
          <Icon name="add_circle" className="text-[18px]" />
          Create New Event
        </button>
      </div>

      {error !== null ? (
        <ErrorBox>{messageFor(error)}</ErrorBox>
      ) : !events ? (
        <Loading what="Loading events" />
      ) : events.length === 0 ? (
        <div className={`${card} p-space-xl text-center`}>
          <Icon name="event" className="text-outline text-[40px]" />
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-2">No events yet. Create the first one.</p>
        </div>
      ) : (
        <div className={`${card} overflow-hidden`}>
          <div className="w-full overflow-x-auto">
            <table className="w-full min-w-[42rem] text-left border-collapse">
              <thead>
                <tr className="bg-surface-container-low/60 text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
                  <th scope="col" className="py-3.5 px-space-lg font-semibold">Event</th>
                  <th scope="col" className="py-3.5 px-space-md font-semibold">Starts</th>
                  <th scope="col" className="py-3.5 px-space-md font-semibold">Status</th>
                  <th scope="col" className="py-3.5 px-space-md font-semibold">Seats left</th>
                  <th scope="col" className="py-3.5 px-space-lg font-semibold">Waitlist</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container font-body-md text-body-md text-on-surface">
                {events.map((e) => {
                  const s = statusOf(e);
                  return (
                    <tr key={e.id} className="hover:bg-surface-container-low/40 transition-colors">
                      <td className="py-4 px-space-lg">
                        <Link to={`/admin/events/${e.id}`} className="font-headline-sm text-headline-sm text-primary hover:underline">{e.title}</Link>
                      </td>
                      <td className="py-4 px-space-md text-on-surface-variant whitespace-nowrap">
                        {formatDateLong(e.starts_at)} · {formatTimeZoned(e.starts_at)}
                      </td>
                      <td className="py-4 px-space-md"><Pill tone={s.tone} dot>{s.text}</Pill></td>
                      <td className="py-4 px-space-md font-code-tabular text-code-tabular tabular-nums whitespace-nowrap">{e.seats_left} / {e.capacity}</td>
                      <td className="py-4 px-space-lg font-code-tabular text-code-tabular tabular-nums">{e.waitlist_count}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {creating && <CreateEventModal onClose={() => setCreating(false)} />}
    </section>
  );
}
