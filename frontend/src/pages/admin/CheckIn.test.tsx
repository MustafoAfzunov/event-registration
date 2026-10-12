import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { EVENT, FakeEventSource, STATS, apiError, installEventSource, mockApi } from "../../test/fakes";
import { HEALTH, renderAt } from "../../test/render";

const RECENT = "GET /api/admin/events/ev-1/registrations?status=checked_in";
const BASE = {
  ...HEALTH,
  "GET /api/admin/me": { body: { role: "organizer" } },
  "GET /api/events/ev-1": { body: EVENT },
  [RECENT]: { body: [] },
};
const CHECKIN = "POST /api/admin/events/ev-1/checkin";

async function scan(user: ReturnType<typeof renderAt>["user"], code: string) {
  const input = await screen.findByLabelText("Ticket code");
  await user.clear(input);
  await user.type(input, `${code}{Enter}`);
  return input as HTMLInputElement;
}

describe("CheckIn", () => {
  beforeEach(installEventSource);

  it("shows_idle_state_before_first_scan", async () => {
    mockApi(BASE);
    renderAt("/admin/events/ev-1/checkin");
    expect(await screen.findByText(/Waiting for a ticket/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("success_clears_input_and_shows_green", async () => {
    const calls = mockApi({ ...BASE, [CHECKIN]: { body: { result: "checked_in", email: "a@example.com", checked_in_at: "2099-11-01T15:01:00Z" } } });
    const { user } = renderAt("/admin/events/ev-1/checkin");
    const input = await scan(user, "abcd efgh");

    const result = await screen.findByRole("alert");
    expect(result).toHaveAttribute("data-result", "success");
    expect(result).toHaveTextContent("Welcome!");
    expect(result).toHaveTextContent("Verified");
    expect(result).toHaveTextContent("a@example.com");
    expect(input.value).toBe("");
    expect(input).toHaveFocus();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ code: "abcd efgh" });
  });

  it("already_checked_in_shows_red_with_time", async () => {
    mockApi({ ...BASE, [CHECKIN]: apiError(409, "already_checked_in", { checked_in_at: "2099-11-01T15:01:00Z", email: "a@example.com" }) });
    const { user } = renderAt("/admin/events/ev-1/checkin");
    const input = await scan(user, "ABCD-EFGH");

    const result = await screen.findByRole("alert");
    expect(result).toHaveAttribute("data-result", "error");
    expect(result).toHaveTextContent("Already used");
    expect(result).toHaveTextContent("a@example.com");
    expect(result).toHaveTextContent("Code ABCD-EFGH");
    expect(input.value).toBe("ABCD-EFGH"); // kept (and selected) for correction
  });

  it.each([
    ["ticket_cancelled", 409, "Ticket cancelled", "warning"],
    ["ticket_waitlisted", 409, "No seat (waitlist)", "warning"],
    ["ticket_not_found", 404, "Unknown code", "error"],
    ["invalid_code_format", 422, "Not a ticket code", "warning"],
    ["event_cancelled", 409, "Check-in failed", "error"],
  ])("error_%s_has_its_own_message", async (code, status, title, variant) => {
    mockApi({ ...BASE, [CHECKIN]: apiError(status, code, { email: "x@example.com" }) });
    const { user } = renderAt("/admin/events/ev-1/checkin");
    await scan(user, "ZZZZ-9999");
    const result = await screen.findByRole("alert");
    expect(result).toHaveAttribute("data-result", variant);
    expect(result).toHaveTextContent(title);
  });

  it("escape_clears_the_code", async () => {
    mockApi(BASE);
    const { user } = renderAt("/admin/events/ev-1/checkin");
    const input = (await screen.findByLabelText("Ticket code")) as HTMLInputElement;
    await user.type(input, "ABCD");
    expect(input.value).toBe("ABCD");
    await user.keyboard("{Escape}");
    expect(input.value).toBe("");
  });

  it("shows_live_arrived_counter", async () => {
    mockApi(BASE);
    renderAt("/admin/events/ev-1/checkin");
    await screen.findByRole("heading", { name: /Check-in: PyCon Meetup/ });
    FakeEventSource.latest("/api/admin/events/ev-1/stream").emit("stats", { ...STATS, checked_in: 1, registered: 3 });
    expect(screen.getByLabelText("Arrived")).toHaveTextContent("1 / 3 arrived");
    expect(screen.getByText("(33.3%)")).toBeInTheDocument();
  });

  it("recent_checkins_lists_latest_first_and_refreshes_live", async () => {
    let rows = [
      { id: "r1", email: "early@example.com", status: "checked_in", ticket_code: "AAAA-1111", waitlist_position: null, created_at: "2099-10-01T10:00:00Z", checked_in_at: "2099-11-01T15:01:00Z" },
      { id: "r2", email: "late@example.com", status: "checked_in", ticket_code: "BBBB-2222", waitlist_position: null, created_at: "2099-10-01T10:01:00Z", checked_in_at: "2099-11-01T15:09:00Z" },
    ];
    mockApi({ ...BASE, [RECENT]: () => ({ body: rows }) });
    renderAt("/admin/events/ev-1/checkin");

    const table = await screen.findByRole("table", { name: "Recent check-ins" });
    const emails = () => within(table).getAllByRole("row").slice(1).map((r) => r.textContent ?? "");
    expect(emails()[0]).toContain("late@example.com"); // newest first
    expect(emails()[1]).toContain("early@example.com");

    rows = [{ ...rows[1]!, id: "r3", email: "newest@example.com", ticket_code: "CCCC-3333", checked_in_at: "2099-11-01T15:30:00Z" }, ...rows];
    FakeEventSource.latest("/api/admin/events/ev-1/stream").emit("stats", { ...STATS, checked_in: 3 });
    expect(await within(await screen.findByRole("table", { name: "Recent check-ins" })).findByText(/newest@example.com/)).toBeInTheDocument();
  });

  it("recent_checkins_empty_state", async () => {
    mockApi(BASE);
    renderAt("/admin/events/ev-1/checkin");
    expect(await screen.findByText(/No check-ins yet/)).toBeInTheDocument();
  });
});
