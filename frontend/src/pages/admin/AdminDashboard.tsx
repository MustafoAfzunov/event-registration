import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import {
  api,
  streams,
  type AdminRegistration,
  type PublicEvent,
  type RegistrationStatus,
  type Stats,
} from "../../api";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { Pagination } from "../../components/Pagination";
import { adminContainer, btnDanger, btnPrimary, btnSecondary, btnSoft, card, input, label } from "../../components/styles";
import { Toast } from "../../components/Toast";
import { ErrorBox, LiveBadge, Loading, Pill, type Tone } from "../../components/ui";
import { messageFor } from "../../errors";
import {
  formatDateLong,
  formatDateTime,
  formatPercent,
  formatTimeZoned,
  fromLocalInput,
  initialsOf,
  percent,
  plural,
  timeAgo,
  toLocalInput,
} from "../../format";
import { useEventStream } from "../../useEventStream";
import { useNow } from "../../useNow";

const PAGE_SIZE = 10;

type Tab = { label: string; status?: RegistrationStatus; count?: (s: Stats) => number };
const TABS: Tab[] = [
  { label: "All", count: (s) => s.confirmed + s.checked_in + s.waitlisted + s.cancelled },
  { label: "Confirmed", status: "confirmed", count: (s) => s.confirmed },
  { label: "Checked in", status: "checked_in", count: (s) => s.checked_in },
  { label: "Waitlisted", status: "waitlisted", count: (s) => s.waitlisted },
  { label: "Cancelled", status: "cancelled", count: (s) => s.cancelled },
];

const ROW_PILL: Record<RegistrationStatus, Tone> = {
  confirmed: "primary",
  checked_in: "ok",
  waitlisted: "warn",
  cancelled: "neutral",
};

function MetricCard({ title, icon, iconBox, children }: { title: string; icon: string; iconBox: string; children: ReactNode }) {
  return (
    <div className={`${card} flex flex-col justify-between p-space-lg hover:shadow-md transition-shadow`}>
      <div className="flex items-center justify-between mb-space-sm">
        <h2 className="font-label-md text-label-md text-on-surface-variant uppercase tracking-wider">{title}</h2>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${iconBox}`}>
          <Icon name={icon} className="text-[20px]" />
        </div>
      </div>
      {children}
    </div>
  );
}

function Counters({ stats, lastEntry, onRaiseCapacity }: { stats: Stats; lastEntry: string | null; onRaiseCapacity: () => void }) {
  const now = useNow(30_000);
  const occupancy = percent(stats.registered, stats.capacity);
  const inVenue = percent(stats.checked_in, stats.registered);
  const almostFull = occupancy >= 80;
  return (
    <div role="group" aria-label="Live counters" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-gutter">
      <MetricCard title="Registered" icon="confirmation_number" iconBox="bg-primary-fixed text-primary">
        <div className="flex items-baseline gap-2 mb-2">
          <span aria-label="Registered" className="font-headline-lg text-headline-lg text-on-surface font-bold tabular-nums">{stats.registered}</span>
          <span className="font-body-md text-body-md text-on-surface-variant font-medium">/ {stats.capacity} seats</span>
        </div>
        <div className="w-full flex flex-col gap-1.5 mt-2">
          <div className="w-full bg-surface-container rounded-full h-2 overflow-hidden">
            <div className="bg-primary h-2 rounded-full transition-all duration-500" style={{ width: `${occupancy}%` }} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 font-body-sm text-body-sm text-on-surface-variant tabular-nums">
            <span>{formatPercent(occupancy)} occupancy</span>
            <span className={`font-code-tabular ${almostFull ? "text-error" : ""} font-medium`}>{plural(stats.seats_left, "seat")} remaining</span>
          </div>
        </div>
      </MetricCard>

      <MetricCard title="Checked in" icon="how_to_reg" iconBox="bg-secondary-fixed text-secondary">
        <div className="flex items-baseline gap-2 mb-2 flex-wrap">
          <span aria-label="Checked in" className="font-headline-lg text-headline-lg text-on-surface font-bold tabular-nums">{stats.checked_in}</span>
          <span className="font-body-md text-body-md text-secondary flex items-center gap-1 font-medium tabular-nums">
            {stats.checked_in > 0 && <span aria-hidden="true" className="w-2 h-2 rounded-full bg-secondary animate-ping" />}
            {formatPercent(inVenue)} arrived
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 mt-2 font-body-sm text-body-sm text-on-surface-variant">
          <span>
            <span aria-label="Not arrived yet" className="font-semibold text-on-surface tabular-nums">{stats.confirmed}</span> not arrived yet
          </span>
          <span>{lastEntry ? `Last entry ${timeAgo(lastEntry, now)}` : "No check-ins yet"}</span>
        </div>
      </MetricCard>

      <MetricCard title="Waitlist" icon="hourglass_top" iconBox="bg-tertiary-fixed text-tertiary">
        <div className="flex items-baseline gap-2 mb-2 flex-wrap">
          <span aria-label="Waitlisted" className="font-headline-lg text-headline-lg text-on-surface font-bold tabular-nums">{stats.waitlisted}</span>
          <span className="font-body-sm text-body-sm text-tertiary font-medium">First in line is promoted automatically</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 mt-2 pt-1">
          <span className="font-label-sm text-label-sm text-on-surface-variant">{stats.cancelled} cancelled so far</span>
          <button type="button" onClick={onRaiseCapacity} className="font-label-sm text-label-sm text-primary hover:underline font-semibold">
            Raise capacity
          </button>
        </div>
      </MetricCard>

      <MetricCard title="Email delivery" icon="mail" iconBox="bg-primary-fixed-dim text-primary">
        <div className="flex items-baseline gap-2 mb-2">
          <span aria-label="Emails sent" className="font-headline-lg text-headline-lg text-on-surface font-bold tabular-nums">{stats.emails.sent}</span>
          <span className="font-body-md text-body-md text-on-surface-variant font-medium">sent</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 font-body-sm text-body-sm text-on-surface-variant mt-2 tabular-nums">
          <span>{stats.emails.pending + stats.emails.sending} pending</span>
          <span className={stats.emails.failed > 0 ? "text-error font-semibold" : ""}>
            {stats.emails.failed > 0 ? `${plural(stats.emails.failed, "email")} could not be delivered` : "0 failed"}
          </span>
        </div>
      </MetricCard>
    </div>
  );
}

function normalizeCode(text: string): string {
  return text.replace(/[\s-]/g, "").toLowerCase();
}

function Participants({ rows, error, stats }: { rows: AdminRegistration[] | null; error: unknown; stats: Stats | null }) {
  const [tab, setTab] = useState(0);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const status = TABS[tab]?.status;

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const qc = normalizeCode(query);
    return (rows ?? []).filter(
      (r) =>
        (!status || r.status === status) &&
        (!q || r.email.toLowerCase().includes(q) || (qc && normalizeCode(r.ticket_code).includes(qc))),
    );
  }, [rows, status, query]);

  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const shown = visible.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  return (
    <section className="w-full bg-surface-container-lowest rounded-2xl shadow-sm flex flex-col overflow-hidden" aria-labelledby="participants-heading">
      <div className="p-space-lg bg-surface-container-low flex flex-col gap-space-md">
        <h2 id="participants-heading" className="font-headline-sm text-headline-sm text-on-surface">Participants</h2>
        <div className="flex flex-col md:flex-row gap-space-md md:items-center justify-between">
          <div className="relative flex-1 max-w-md">
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px]" />
            <input
              type="search"
              aria-label="Search participants"
              placeholder="Search by email or ticket code…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
              className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-surface text-on-surface font-body-sm text-body-sm placeholder:text-outline focus:outline-none focus:bg-surface-container-lowest transition-colors shadow-sm"
            />
          </div>
          <div role="tablist" aria-label="Filter participants" className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
            {TABS.map((t, i) => (
              <button
                key={t.label}
                role="tab"
                type="button"
                aria-selected={i === tab}
                onClick={() => {
                  setTab(i);
                  setPage(1);
                }}
                className={`px-3.5 py-1.5 rounded-full font-label-sm text-label-sm font-semibold whitespace-nowrap transition-all ${
                  i === tab ? "bg-primary text-on-primary shadow-sm" : "bg-surface-container text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                {t.label}
                {stats && t.count && <span className="ml-1 tabular-nums opacity-80">({t.count(stats)})</span>}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error !== null ? (
        <div className="p-space-lg"><ErrorBox>{messageFor(error)}</ErrorBox></div>
      ) : !rows ? (
        <div className="px-space-lg"><Loading what="Loading participants" /></div>
      ) : visible.length === 0 ? (
        <p className="p-space-xl text-center font-body-md text-body-md text-on-surface-variant">
          {rows.length === 0 ? "Nobody here yet." : "Nobody matches this filter."}
        </p>
      ) : (
        <div className="w-full overflow-x-auto">
          <table aria-label="Participants" className="w-full min-w-[44rem] text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low/60 text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider">
                <th scope="col" className="py-3.5 px-space-lg font-semibold">Attendee</th>
                <th scope="col" className="py-3.5 px-space-md font-semibold">Ticket</th>
                <th scope="col" className="py-3.5 px-space-md font-semibold">Registered</th>
                <th scope="col" className="py-3.5 px-space-md font-semibold">Status</th>
                <th scope="col" className="py-3.5 px-space-lg font-semibold">Checked in</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container font-body-md text-body-md text-on-surface">
              {shown.map((r) => (
                <tr key={r.id} className="hover:bg-surface-container-low/40 transition-colors">
                  <td className="py-4 px-space-lg">
                    <div className="flex items-center gap-space-sm min-w-0">
                      <div aria-hidden="true" className="w-9 h-9 rounded-full bg-surface-variant text-on-surface-variant flex items-center justify-center font-headline-sm text-headline-sm font-bold shrink-0">
                        {initialsOf(r.email)}
                      </div>
                      <span className="font-body-md text-body-md text-on-surface break-words">{r.email}</span>
                    </div>
                  </td>
                  <td className="py-4 px-space-md">
                    <code className={`font-code-tabular text-code-tabular px-2 py-1 rounded bg-surface-container whitespace-nowrap ${r.status === "waitlisted" || r.status === "cancelled" ? "text-outline" : "text-on-surface"}`}>
                      {r.ticket_code}
                    </code>
                  </td>
                  <td className="py-4 px-space-md font-body-sm text-body-sm text-on-surface-variant whitespace-nowrap">{formatDateTime(r.created_at)}</td>
                  <td className="py-4 px-space-md">
                    <Pill tone={ROW_PILL[r.status]} dot={r.status === "checked_in"} className="capitalize font-bold">
                      {r.status === "waitlisted" ? `waitlisted #${r.waitlist_position}` : r.status.replace("_", " ")}
                    </Pill>
                  </td>
                  <td className="py-4 px-space-lg font-body-sm text-body-sm text-on-surface-variant whitespace-nowrap">
                    {r.checked_in_at ? formatDateTime(r.checked_in_at) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows && visible.length > 0 && <Pagination page={current} pageSize={PAGE_SIZE} total={visible.length} noun="participants" onPage={setPage} />}
    </section>
  );
}

type ModalTab = "reschedule" | "details";

function EventModal({
  event,
  stats,
  initialTab,
  onClose,
  onChanged,
  onToast,
}: {
  event: PublicEvent;
  stats: Stats | null;
  initialTab: ModalTab;
  onClose: () => void;
  onChanged: (e: PublicEvent) => void;
  onToast: (message: string) => void;
}) {
  const [tab, setTab] = useState<ModalTab>(initialTab);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState(event.title);
  const [description, setDescription] = useState(event.description);
  const [capacity, setCapacity] = useState(String(event.capacity));
  const [startsAt, setStartsAt] = useState(toLocalInput(event.starts_at));

  // Everyone with a stake gets the "new date" email: seat holders (registered) and the waitlist.
  const toNotify = stats ? stats.registered + stats.waitlisted : null;

  function switchTab(next: ModalTab) {
    setTab(next);
    setError(null);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const saveDetails = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const saved = await api.updateEvent(event.id, { title, description, capacity: Number(capacity) });
      onChanged(saved);
      onToast(saved.promoted_count ? `Saved. ${plural(saved.promoted_count, "person", "people")} moved from the waitlist.` : "Saved.");
      onClose();
    });
  };

  const reschedule = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const r = await api.reschedule(event.id, fromLocalInput(startsAt));
      onChanged(r.event);
      onToast(
        r.changed
          ? `Moved to ${formatDateTime(r.event.starts_at)}. ${plural(r.notified, "participant")} notified by email.`
          : "Same date: nothing changed.",
      );
      onClose();
    });
  };

  const cancelEvent = () => {
    if (!window.confirm("Cancel this event? Everyone registered or waiting will be emailed.")) return;
    void run(async () => {
      const r = await api.cancelEvent(event.id);
      onChanged(r.event);
      onToast(`Event cancelled. ${plural(r.notified, "participant")} notified.`);
      onClose();
    });
  };

  return (
    <Modal
      title="Edit or reschedule event"
      subtitle="Reschedule notifies everyone by email"
      icon="edit_calendar"
      onClose={onClose}
    >
      <div role="tablist" aria-label="Edit event" className="flex items-center gap-1.5">
        {(
          [
            ["reschedule", "Reschedule"],
            ["details", "Details"],
          ] as const
        ).map(([id, text]) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => switchTab(id)}
            className={`px-3.5 py-1.5 rounded-full font-label-sm text-label-sm font-semibold transition-all ${
              tab === id ? "bg-primary text-on-primary shadow-sm" : "bg-surface-container text-on-surface-variant hover:bg-surface-container-high"
            }`}
          >
            {text}
          </button>
        ))}
      </div>

      {tab === "reschedule" ? (
        <form className="flex flex-col gap-space-md" onSubmit={reschedule} aria-label="Reschedule">
          <div>
            <label htmlFor="new-date" className={label}>New date and time (your local time)</label>
            <input id="new-date" type="datetime-local" required value={startsAt} onChange={(e) => setStartsAt(e.target.value)} className={input} />
          </div>
          <div className="p-space-md rounded-xl bg-surface-container flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-label-sm text-label-sm uppercase font-bold text-primary flex items-center gap-1.5">
                <Icon name="campaign" className="text-[16px]" /> Email notification
              </span>
              <Pill tone="ok">Ready</Pill>
            </div>
            <p className="font-body-sm text-body-sm text-on-surface">
              {stats ? (
                <>
                  Everyone with a stake gets an email with the new date:{" "}
                  <strong>{plural(stats.registered, "registered participant")}</strong> and{" "}
                  <strong>{plural(stats.waitlisted, "waitlisted person", "waitlisted people")}</strong>. Pending reminders for the
                  old date are dropped, and one reminder follows for the new date.
                </>
              ) : (
                "Everyone registered or waiting gets an email with the new date."
              )}
            </p>
          </div>
          {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
          <div className="flex items-center justify-end gap-space-sm">
            <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
            <button type="submit" className={btnPrimary} disabled={busy}>
              <Icon name="send" className="text-[18px]" />
              {busy ? "Working…" : toNotify ? `Confirm & Notify ${toNotify}` : "Confirm new date"}
            </button>
          </div>
        </form>
      ) : (
        <>
          <form className="flex flex-col gap-space-md" onSubmit={saveDetails} aria-label="Edit event">
            <div>
              <label htmlFor="edit-title" className={label}>Title</label>
              <input id="edit-title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} className={input} />
            </div>
            <div>
              <label htmlFor="edit-description" className={label}>Description</label>
              <textarea id="edit-description" rows={3} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} className={input} />
            </div>
            <div>
              <label htmlFor="edit-capacity" className={label}>Seat limit</label>
              <input id="edit-capacity" type="number" min={1} max={100000} required value={capacity} onChange={(e) => setCapacity(e.target.value)} className={input} />
              <p className="font-body-sm text-body-sm text-on-surface-variant mt-1">Raising it moves people from the waitlist automatically, first in line first.</p>
            </div>
            {error !== null && <ErrorBox>{messageFor(error)}</ErrorBox>}
            <div className="flex items-center justify-end gap-space-sm">
              <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
              <button type="submit" className={btnPrimary} disabled={busy}>Save</button>
            </div>
          </form>
          <div className="pt-space-md border-t border-surface-container flex flex-col gap-space-sm">
            <h3 className="font-label-lg text-label-lg text-on-surface">Cancel this event</h3>
            <p className="font-body-sm text-body-sm text-on-surface-variant">Everyone registered or waiting is emailed, and registration closes for good.</p>
            <button type="button" className={`${btnDanger} self-start`} onClick={cancelEvent} disabled={busy}>
              <Icon name="event_busy" className="text-[18px]" />
              Cancel event and notify everyone
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

function statusPill(event: PublicEvent, now: number): { tone: Tone; text: string; pulse: boolean } {
  if (event.status === "cancelled") return { tone: "error", text: "Cancelled", pulse: false };
  if (new Date(event.starts_at).getTime() <= now) return { tone: "neutral", text: "Started", pulse: false };
  return { tone: "ok", text: "Registration open", pulse: true };
}

export function AdminDashboard() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rows, setRows] = useState<AdminRegistration[] | null>(null);
  const [rowsError, setRowsError] = useState<unknown>(null);
  const [modal, setModal] = useState<ModalTab | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const live = useEventStream<Stats>(streams.stats(eventId), "stats");
  const now = useNow(30_000);

  useEffect(() => {
    api.getEvent(eventId).then(setEvent, setError);
    api.stats(eventId).then(setStats, setError);
  }, [eventId]);

  // The participant list is re-read on every live frame (a registration, cancel, check-in, ...).
  useEffect(() => {
    let current = true;
    api.registrations(eventId).then(
      (r) => current && (setRows(r), setRowsError(null)),
      (err) => current && setRowsError(err),
    );
    return () => {
      current = false;
    };
  }, [eventId, live.data]);

  const lastEntry = useMemo(() => {
    const times = (rows ?? []).map((r) => r.checked_in_at).filter((t): t is string => t !== null);
    return times.length ? times.reduce((a, b) => (a > b ? a : b)) : null;
  }, [rows]);

  if (error) return <div className={adminContainer}><ErrorBox>{messageFor(error)}</ErrorBox></div>;
  if (!event) return <div className={adminContainer}><Loading what="Loading event" /></div>;
  const current = live.data ?? stats;
  const pill = statusPill(event, now);

  return (
    <article className={`${adminContainer} flex flex-col gap-space-xl`}>
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-lg">
        <div className="flex flex-col gap-space-xs min-w-0">
          <div className="flex items-center gap-space-sm flex-wrap">
            <Pill tone={pill.tone} dot pulse={pill.pulse}>{pill.text}</Pill>
            <LiveBadge status={live.status} />
          </div>
          <h1 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface tracking-tight break-words">
            {event.title}
          </h1>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            {formatDateLong(event.starts_at)} · {formatTimeZoned(event.starts_at)} ·{" "}
            <Link to={`/events/${event.id}`} className="text-primary hover:underline">public page</Link>
          </p>
        </div>
        <div className="flex items-center gap-space-sm flex-wrap">
          {event.status === "scheduled" && (
            <button type="button" className={btnSoft} onClick={() => setModal("reschedule")}>
              <Icon name="calendar_month" className="text-[18px]" />
              Reschedule / Edit Event
            </button>
          )}
          <Link to="/admin?new=1" className={btnPrimary}>
            <Icon name="add_circle" className="text-[18px]" />
            Create New Event
          </Link>
        </div>
      </div>

      {live.status === "expired" && (
        <ErrorBox>
          Your login expired. <Link to={`/admin/login?next=/admin/events/${eventId}`} className="underline font-semibold">Log in again</Link> for live updates.
        </ErrorBox>
      )}

      {current ? (
        <Counters stats={current} lastEntry={lastEntry} onRaiseCapacity={() => setModal("details")} />
      ) : (
        <Loading what="Loading counters" />
      )}

      <Participants rows={rows} error={rowsError} stats={current} />

      {modal && (
        <EventModal
          event={event}
          stats={current}
          initialTab={modal}
          onClose={() => setModal(null)}
          onChanged={setEvent}
          onToast={setToast}
        />
      )}
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </article>
  );
}

