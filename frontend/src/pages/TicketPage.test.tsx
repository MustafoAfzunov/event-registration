import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EVENT, apiError, mockApi } from "../test/fakes";
import { HEALTH, renderAt } from "../test/render";

const confirmed = { event: EVENT, email: "a@example.com", status: "confirmed", ticket_code: "ABCD-EFGH", waitlist_position: null, checked_in_at: null };

describe("TicketPage", () => {
  it("shows_ticket_code_and_cancels", async () => {
    let current: Record<string, unknown> = confirmed;
    const calls = mockApi({
      ...HEALTH,
      "GET /api/registrations/tok": () => ({ body: current }),
      "POST /api/registrations/tok/cancel": () => {
        current = { ...confirmed, status: "cancelled", ticket_code: null };
        return { body: { status: "cancelled" } };
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user } = renderAt("/r/tok");

    expect(await screen.findByLabelText("Ticket code")).toHaveTextContent("ABCD-EFGH");
    await user.click(screen.getByRole("button", { name: "Cancel my registration" }));

    expect(await screen.findByText(/This registration is cancelled/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Ticket code")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("does_nothing_if_cancel_not_confirmed", async () => {
    const calls = mockApi({ ...HEALTH, "GET /api/registrations/tok": { body: confirmed } });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { user } = renderAt("/r/tok");
    await user.click(await screen.findByRole("button", { name: "Cancel my registration" }));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("shows_waitlist_position_without_code", async () => {
    mockApi({ ...HEALTH, "GET /api/registrations/tok": { body: { ...confirmed, status: "waitlisted", ticket_code: null, waitlist_position: 2 } } });
    renderAt("/r/tok");
    expect(await screen.findByText(/on the waitlist/)).toHaveTextContent("#2");
    expect(screen.queryByLabelText("Ticket code")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave the waitlist" })).toBeInTheDocument();
  });

  it("shows_checked_in_state_without_cancel", async () => {
    mockApi({ ...HEALTH, "GET /api/registrations/tok": { body: { ...confirmed, status: "checked_in", checked_in_at: "2099-11-01T15:05:00Z" } } });
    renderAt("/r/tok");
    expect(await screen.findByText(/Checked in/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });

  it("shows_error_when_cancel_fails", async () => {
    mockApi({
      ...HEALTH,
      "GET /api/registrations/tok": { body: confirmed },
      "POST /api/registrations/tok/cancel": apiError(409, "already_checked_in"),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user } = renderAt("/r/tok");
    await user.click(await screen.findByRole("button", { name: "Cancel my registration" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already used for check-in");
  });

  it("shows_invalid_link", async () => {
    mockApi({ ...HEALTH, "GET /api/registrations/bad": apiError(404, "registration_not_found") });
    renderAt("/r/bad");
    expect(await screen.findByRole("alert")).toHaveTextContent("This ticket link is not valid.");
  });
});
