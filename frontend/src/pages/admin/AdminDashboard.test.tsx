import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EVENT, FakeEventSource, STATS, apiError, installEventSource, mockApi } from "../../test/fakes";
import { HEALTH, renderAt } from "../../test/render";

const person = (n: number, over: Record<string, unknown> = {}) => ({
  id: `r${n}`,
  email: `person${n}@example.com`,
  status: "confirmed",
  ticket_code: `AAAA-${String(1000 + n)}`,
  waitlist_position: null,
  created_at: "2099-10-01T10:00:00Z",
  checked_in_at: null,
  ...over,
});
const PEOPLE = [
  person(1, { email: "a@example.com", ticket_code: "AAAA-1111" }),
  person(2, { email: "w@example.com", status: "waitlisted", ticket_code: "WWWW-2222", waitlist_position: 1 }),
];
const LIST = "GET /api/admin/events/ev-1/registrations";
const BASE = {
  ...HEALTH,
  "GET /api/admin/me": { body: { role: "organizer" } },
  "GET /api/events/ev-1": { body: EVENT },
  "GET /api/admin/events/ev-1/stats": { body: STATS },
  [LIST]: { body: PEOPLE },
};
const counter = (label: string) => within(screen.getByLabelText("Live counters")).getByLabelText(label);
type User = ReturnType<typeof renderAt>["user"];

async function openModal(user: User, tab: "Reschedule" | "Details") {
  await user.click(await screen.findByRole("button", { name: "Reschedule / Edit Event" }));
  const dialog = await screen.findByRole("dialog", { name: "Edit or reschedule event" });
  await user.click(within(dialog).getByRole("tab", { name: tab }));
  return dialog;
}

describe("AdminDashboard", () => {
  beforeEach(installEventSource);

  it("renders_live_counts_and_refreshes_participants", async () => {
    const calls = mockApi(BASE);
    renderAt("/admin/events/ev-1");
    expect(await screen.findByRole("heading", { name: "PyCon Meetup" })).toBeInTheDocument();
    expect(counter("Registered")).toHaveTextContent("1");
    expect(counter("Checked in")).toHaveTextContent("0");
    expect(await screen.findByText("waitlisted #1")).toBeInTheDocument();
    const listCalls = () => calls.filter((c) => c.path.startsWith("/api/admin/events/ev-1/registrations")).length;
    const before = listCalls();

    FakeEventSource.latest("/api/admin/events/ev-1/stream").emit("stats", { ...STATS, confirmed: 0, checked_in: 1 });

    expect(counter("Checked in")).toHaveTextContent("1");
    expect(counter("Not arrived yet")).toHaveTextContent("0");
    expect(screen.getByLabelText("Live updates: live")).toBeInTheDocument();
    await vi.waitFor(() => expect(listCalls()).toBeGreaterThan(before));
  });

  it("shows_capacity_email_and_waitlist_cards_from_stats", async () => {
    mockApi({ ...BASE, "GET /api/admin/events/ev-1/stats": { body: { ...STATS, registered: 3, confirmed: 3, seats_left: 0, waitlisted: 5, cancelled: 2, emails: { pending: 2, sending: 1, sent: 9, failed: 2, skipped: 0 } } } });
    renderAt("/admin/events/ev-1");
    const group = await screen.findByLabelText("Live counters");
    expect(group).toHaveTextContent("100% occupancy"); // 3 of 3 seats
    expect(group).toHaveTextContent("0 seats remaining");
    expect(counter("Waitlisted")).toHaveTextContent("5");
    expect(counter("Emails sent")).toHaveTextContent("9");
    expect(group).toHaveTextContent("3 pending"); // pending + sending
    expect(group).toHaveTextContent("2 emails could not be delivered");
    expect(group).toHaveTextContent("No check-ins yet");
  });

  it("filters_participants_by_status", async () => {
    const calls = mockApi(BASE);
    const { user } = renderAt("/admin/events/ev-1");
    const table = await screen.findByRole("table", { name: "Participants" });
    expect(within(table).getByText("a@example.com")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /^Waitlisted/ }));

    // filtering is client-side on the one list that was loaded (no extra request)
    expect(within(table).queryByText("a@example.com")).not.toBeInTheDocument();
    expect(within(table).getByText("w@example.com")).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes("?status="))).toBe(false);
    expect(screen.getByRole("tab", { name: /^Waitlisted/ })).toHaveAttribute("aria-selected", "true");
  });

  it("search_filters_by_email_and_ticket_code", async () => {
    mockApi(BASE);
    const { user } = renderAt("/admin/events/ev-1");
    const table = await screen.findByRole("table", { name: "Participants" });
    const search = screen.getByRole("searchbox", { name: "Search participants" });

    await user.type(search, "WWWW 2222"); // code typed the way people read it
    expect(within(table).queryByText("a@example.com")).not.toBeInTheDocument();
    expect(within(table).getByText("w@example.com")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "A@EXAMPLE");
    expect(within(table).getByText("a@example.com")).toBeInTheDocument();
    expect(within(table).queryByText("w@example.com")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "nobody-matches");
    expect(await screen.findByText("Nobody matches this filter.")).toBeInTheDocument();
  });

  it("paginates_long_participant_lists", async () => {
    mockApi({ ...BASE, [LIST]: { body: Array.from({ length: 25 }, (_, i) => person(i + 1)) } });
    const { user } = renderAt("/admin/events/ev-1");
    const table = await screen.findByRole("table", { name: "Participants" });
    expect(screen.getByText(/Showing/)).toHaveTextContent("Showing 1–10 of 25 participants");
    expect(within(table).getAllByRole("row")).toHaveLength(11); // header + 10

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/Showing/)).toHaveTextContent("Showing 11–20 of 25 participants");
    expect(within(table).getByText("person11@example.com")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "3" }));
    expect(screen.getByText(/Showing/)).toHaveTextContent("Showing 21–25 of 25 participants");
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("reschedules_with_iso_time_and_reports_notified", async () => {
    const calls = mockApi({
      ...BASE,
      "GET /api/admin/events/ev-1/stats": { body: { ...STATS, registered: 3, confirmed: 3, waitlisted: 2 } },
      "POST /api/admin/events/ev-1/reschedule": (body) => ({
        body: { event: { ...EVENT, starts_at: (body as { starts_at: string }).starts_at }, notified: 4, changed: true },
      }),
    });
    const { user } = renderAt("/admin/events/ev-1");
    const dialog = await openModal(user, "Reschedule");
    // the button and the info box state how many people will be emailed (registered + waitlisted)
    expect(within(dialog).getByText(/3 registered participants/)).toBeInTheDocument();
    expect(within(dialog).getByText(/2 waitlisted people/)).toBeInTheDocument();
    const input = within(dialog).getByLabelText("New date and time (your local time)");
    await user.clear(input);
    await user.type(input, "2099-12-24T18:30");
    await user.click(within(dialog).getByRole("button", { name: "Confirm & Notify 5" }));

    expect(await screen.findByText(/4 participants notified by email/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); // closed on success
    const sent = calls.find((c) => c.path.endsWith("/reschedule"))?.body as { starts_at: string };
    expect(sent.starts_at).toBe(new Date("2099-12-24T18:30").toISOString());
  });

  it("shows_capacity_error_with_seats_taken", async () => {
    mockApi({ ...BASE, "PATCH /api/admin/events/ev-1": apiError(409, "capacity_below_taken", { seats_taken: 5 }) });
    const { user } = renderAt("/admin/events/ev-1");
    const dialog = await openModal(user, "Details");
    const capacity = within(dialog).getByLabelText("Seat limit");
    await user.clear(capacity);
    await user.type(capacity, "2");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("lower than the 5 seats already taken");
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // stays open so the value can be fixed
  });

  it("saves_details_and_reports_promotions", async () => {
    mockApi({ ...BASE, "PATCH /api/admin/events/ev-1": { body: { ...EVENT, title: "Renamed", capacity: 5, promoted_count: 2 } } });
    const { user } = renderAt("/admin/events/ev-1");
    const dialog = await openModal(user, "Details");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved. 2 people moved from the waitlist.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Renamed" })).toBeInTheDocument();
  });

  it("raise_capacity_opens_details_tab", async () => {
    mockApi(BASE);
    const { user } = renderAt("/admin/events/ev-1");
    await user.click(await screen.findByRole("button", { name: "Raise capacity" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit or reschedule event" });
    expect(within(dialog).getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByLabelText("Seat limit")).toBeInTheDocument();
  });

  it("modal_closes_on_escape_and_returns_focus_to_its_button", async () => {
    mockApi(BASE);
    const { user } = renderAt("/admin/events/ev-1");
    const opener = await screen.findByRole("button", { name: "Reschedule / Edit Event" });
    await user.click(opener);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("cancel_event_from_details_tab_needs_confirmation", async () => {
    const calls = mockApi({ ...BASE, "POST /api/admin/events/ev-1/cancel": { body: { event: { ...EVENT, status: "cancelled" }, notified: 3, changed: true } } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { user } = renderAt("/admin/events/ev-1");
    const dialog = await openModal(user, "Details");
    const button = within(dialog).getByRole("button", { name: "Cancel event and notify everyone" });

    await user.click(button); // declined: nothing sent
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    await user.click(button); // confirmed
    expect(await screen.findByText("Event cancelled. 3 participants notified.")).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Reschedule / Edit Event" })).not.toBeInTheDocument();
    // the header's status pill flips to "Cancelled" (the filter tab has the same word, so scope to the header)
    const header = screen.getByRole("heading", { name: "PyCon Meetup" }).parentElement as HTMLElement;
    expect(within(header).getByText("Cancelled")).toBeInTheDocument();
  });

  it("shows_last_entry_from_checked_in_rows", async () => {
    mockApi({ ...BASE, [LIST]: { body: [person(1, { status: "checked_in", checked_in_at: new Date().toISOString() })] } });
    renderAt("/admin/events/ev-1");
    expect(await screen.findByText("Last entry just now")).toBeInTheDocument();
  });

  it("shows_participant_list_error_without_hiding_the_rest", async () => {
    mockApi({ ...BASE, [LIST]: apiError(500, "internal_error") });
    renderAt("/admin/events/ev-1");
    expect(await screen.findByRole("heading", { name: "PyCon Meetup" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(counter("Registered")).toHaveTextContent("1");
  });

  it("asks_to_log_in_again_when_stream_session_expires", async () => {
    mockApi(BASE);
    renderAt("/admin/events/ev-1");
    await screen.findByRole("heading", { name: "PyCon Meetup" });
    const stream = FakeEventSource.latest("/api/admin/events/ev-1/stream");
    stream.emit("session_expired", { reason: "login expired" });
    expect(await screen.findByRole("link", { name: "Log in again" })).toBeInTheDocument();
    expect(stream.readyState).toBe(FakeEventSource.CLOSED);
  });
});
