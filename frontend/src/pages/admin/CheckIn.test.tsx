import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { EVENT, FakeEventSource, STATS, apiError, installEventSource, mockApi } from "../../test/fakes";
import { HEALTH, renderAt } from "../../test/render";

const BASE = { ...HEALTH, "GET /api/admin/me": { body: { role: "organizer" } }, "GET /api/events/ev-1": { body: EVENT } };
const CHECKIN = "POST /api/admin/events/ev-1/checkin";

async function scan(user: ReturnType<typeof renderAt>["user"], code: string) {
  const input = await screen.findByLabelText("Ticket code");
  await user.clear(input);
  await user.type(input, `${code}{Enter}`);
  return input as HTMLInputElement;
}

describe("CheckIn", () => {
  beforeEach(installEventSource);

  it("success_clears_input_and_shows_green", async () => {
    const calls = mockApi({ ...BASE, [CHECKIN]: { body: { result: "checked_in", email: "a@example.com", checked_in_at: "2099-11-01T15:01:00Z" } } });
    const { user } = renderAt("/admin/events/ev-1/checkin");
    const input = await scan(user, "abcd efgh");

    const result = await screen.findByRole("alert");
    expect(result).toHaveClass("result-ok");
    expect(result).toHaveTextContent("Welcome!");
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
    expect(result).toHaveClass("result-error");
    expect(result).toHaveTextContent("Already used");
    expect(result).toHaveTextContent("a@example.com");
    expect(input.value).toBe("ABCD-EFGH"); // kept for correction
  });

  it.each([
    ["ticket_cancelled", "Ticket cancelled"],
    ["ticket_waitlisted", "No seat (waitlist)"],
    ["ticket_not_found", "Unknown code"],
    ["invalid_code_format", "Not a ticket code"],
    ["event_cancelled", "Check-in failed"],
  ])("error_%s_has_its_own_message", async (code, title) => {
    mockApi({ ...BASE, [CHECKIN]: apiError(code === "ticket_not_found" ? 404 : code === "invalid_code_format" ? 422 : 409, code, { email: "x@example.com" }) });
    const { user } = renderAt("/admin/events/ev-1/checkin");
    await scan(user, "ZZZZ-9999");
    const result = await screen.findByRole("alert");
    expect(result).toHaveClass("result-error");
    expect(result).toHaveTextContent(title);
  });

  it("shows_live_arrived_counter", async () => {
    mockApi(BASE);
    renderAt("/admin/events/ev-1/checkin");
    await screen.findByRole("heading", { name: /Check-in: PyCon Meetup/ });
    FakeEventSource.latest("/api/admin/events/ev-1/stream").emit("stats", { ...STATS, checked_in: 1, registered: 3 });
    expect(screen.getByLabelText("Arrived")).toHaveTextContent("1 / 3 arrived");
  });
});
