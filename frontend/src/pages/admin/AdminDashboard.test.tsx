import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EVENT, FakeEventSource, STATS, apiError, installEventSource, mockApi } from "../../test/fakes";
import { HEALTH, renderAt } from "../../test/render";

const PEOPLE = [
  { id: "r1", email: "a@example.com", status: "confirmed", ticket_code: "AAAA-1111", waitlist_position: null, created_at: "2099-10-01T10:00:00Z", checked_in_at: null },
  { id: "r2", email: "w@example.com", status: "waitlisted", ticket_code: "WWWW-2222", waitlist_position: 1, created_at: "2099-10-01T10:01:00Z", checked_in_at: null },
];
const BASE = {
  ...HEALTH,
  "GET /api/admin/me": { body: { role: "organizer" } },
  "GET /api/events/ev-1": { body: EVENT },
  "GET /api/admin/events/ev-1/stats": { body: STATS },
  "GET /api/admin/events/ev-1/registrations": { body: PEOPLE },
  "GET /api/admin/events/ev-1/registrations?status=waitlisted": { body: [PEOPLE[1]] },
};
const counter = (label: string) => within(screen.getByLabelText("Live counters")).getByLabelText(label);

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

  it("filters_participants_by_status", async () => {
    const calls = mockApi(BASE);
    const { user } = renderAt("/admin/events/ev-1");
    await user.click(await screen.findByRole("tab", { name: "Waitlisted" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path.endsWith("?status=waitlisted"))).toBe(true));
    const table = await screen.findByRole("table", { name: "Participants" });
    await vi.waitFor(() => expect(within(table).queryByText("a@example.com")).not.toBeInTheDocument());
    expect(within(table).getByText("w@example.com")).toBeInTheDocument();
  });

  it("reschedules_with_iso_time_and_reports_notified", async () => {
    const calls = mockApi({
      ...BASE,
      "POST /api/admin/events/ev-1/reschedule": (body) => ({
        body: { event: { ...EVENT, starts_at: (body as { starts_at: string }).starts_at }, notified: 4, changed: true },
      }),
    });
    const { user } = renderAt("/admin/events/ev-1");
    const input = await screen.findByLabelText("New date and time (your local time)");
    await user.clear(input);
    await user.type(input, "2099-12-24T18:30");
    await user.click(screen.getByRole("button", { name: "Reschedule and notify everyone" }));

    expect(await screen.findByText(/4 participants notified by email/)).toBeInTheDocument();
    const sent = calls.find((c) => c.path.endsWith("/reschedule"))?.body as { starts_at: string };
    expect(sent.starts_at).toBe(new Date("2099-12-24T18:30").toISOString());
  });

  it("shows_capacity_error_with_seats_taken", async () => {
    mockApi({ ...BASE, "PATCH /api/admin/events/ev-1": apiError(409, "capacity_below_taken", { seats_taken: 5 }) });
    const { user } = renderAt("/admin/events/ev-1");
    const capacity = await screen.findByLabelText("Seat limit");
    await user.clear(capacity);
    await user.type(capacity, "2");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("lower than the 5 seats already taken");
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
