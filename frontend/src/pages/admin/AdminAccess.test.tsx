import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { EVENT, apiError, installEventSource, mockApi } from "../../test/fakes";
import { HEALTH, renderAt } from "../../test/render";

describe("Organizer access", () => {
  beforeEach(installEventSource);

  it("redirects_to_login_then_back_after_login", async () => {
    let loggedIn = false;
    mockApi({
      ...HEALTH,
      "GET /api/admin/me": () => (loggedIn ? { body: { role: "organizer" } } : apiError(401, "unauthorized")),
      "POST /api/admin/login": (body) => {
        if ((body as { password: string }).password !== "secret-password") return apiError(401, "invalid_credentials");
        loggedIn = true;
        return { status: 204 };
      },
      "GET /api/admin/events": { body: [EVENT] },
    });
    const { user } = renderAt("/admin");

    const password = await screen.findByLabelText("Password");
    await user.type(password, "nope");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong password.");

    await user.clear(password);
    await user.type(password, "secret-password");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("heading", { name: "Your events" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "PyCon Meetup" })).toHaveAttribute("href", "/admin/events/ev-1");
  });

  it("creates_event_with_iso_time_and_opens_dashboard", async () => {
    const calls = mockApi({
      ...HEALTH,
      "GET /api/admin/me": { body: { role: "organizer" } },
      "GET /api/admin/events": { body: [] },
      "POST /api/admin/events": (body) => ({ status: 201, body: { ...EVENT, ...(body as object), id: "new-1" } }),
      "GET /api/events/new-1": { body: { ...EVENT, id: "new-1", title: "Fresh" } },
      "GET /api/admin/events/new-1/stats": { body: { capacity: 3, confirmed: 0, checked_in: 0, registered: 0, waitlisted: 0, cancelled: 0, seats_left: 3, emails: { pending: 0, sending: 0, sent: 0, failed: 0, skipped: 0 } } },
      "GET /api/admin/events/new-1/registrations": { body: [] },
    });
    const { user } = renderAt("/admin");
    await user.type(await screen.findByLabelText("Title"), "Fresh");
    await user.type(screen.getByLabelText("Starts at (your local time)"), "2099-05-01T19:00");
    await user.clear(screen.getByLabelText("Seat limit"));
    await user.type(screen.getByLabelText("Seat limit"), "3");
    await user.click(screen.getByRole("button", { name: "Create event" }));

    expect(await screen.findByRole("heading", { name: "Fresh" })).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST" && c.path === "/api/admin/events")?.body;
    expect(sent).toEqual({ title: "Fresh", description: "", starts_at: new Date("2099-05-01T19:00").toISOString(), capacity: 3 });
  });
});
