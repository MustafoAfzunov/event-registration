import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { EVENT, FakeEventSource, apiError, installEventSource, mockApi } from "../test/fakes";
import { HEALTH, renderAt } from "../test/render";

const BASE = { ...HEALTH, "GET /api/events/ev-1": { body: EVENT } };

async function registerAs(user: ReturnType<typeof renderAt>["user"], email: string) {
  await user.type(await screen.findByLabelText("Your email"), email);
  await user.click(screen.getByRole("button", { name: /register|join waitlist/i }));
}

describe("EventPage", () => {
  beforeEach(installEventSource);

  it("shows_details_and_seats_left_updating_live", async () => {
    mockApi(BASE);
    renderAt("/events/ev-1");
    expect(await screen.findByRole("heading", { name: "PyCon Meetup" })).toBeInTheDocument();
    expect(screen.getByText("Talks and pizza")).toBeInTheDocument();
    expect(screen.getByText("2 seats left")).toBeInTheDocument();

    const stream = FakeEventSource.latest("/api/events/ev-1/stream");
    stream.emit("availability", { ...EVENT, event_id: "ev-1", seats_left: 1 });
    expect(screen.getByText("1 seat left")).toBeInTheDocument();
    expect(screen.getByLabelText("Live updates: live")).toBeInTheDocument();

    stream.emit("availability", { ...EVENT, event_id: "ev-1", seats_left: 0, waitlist_count: 2 });
    expect(screen.getByText("Full · 2 people on the waitlist")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join waitlist" })).toBeInTheDocument();
  });

  it("shows_confirmed_after_register", async () => {
    const calls = mockApi({
      ...BASE,
      "POST /api/events/ev-1/registrations": {
        status: 201,
        body: { created: true, status: "confirmed", waitlist_position: null, email: "a@example.com", message: "" },
      },
    });
    const { user } = renderAt("/events/ev-1");
    await registerAs(user, "a@example.com");
    expect(await screen.findByText("You're in!")).toBeInTheDocument();
    expect(screen.getByText(/ticket is on its way to a@example.com/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "a@example.com" });
  });

  it("shows_waitlist_position_when_full", async () => {
    mockApi({
      ...BASE,
      "POST /api/events/ev-1/registrations": {
        status: 201,
        body: { created: true, status: "waitlisted", waitlist_position: 3, email: "w@example.com", message: "" },
      },
    });
    const { user } = renderAt("/events/ev-1");
    await registerAs(user, "w@example.com");
    expect(await screen.findByText("The event is full.")).toBeInTheDocument();
    expect(screen.getByText(/#3 on the waitlist/)).toBeInTheDocument();
  });

  it("shows_already_registered_without_a_second_seat", async () => {
    mockApi({
      ...BASE,
      "POST /api/events/ev-1/registrations": {
        status: 200,
        body: { created: false, status: "confirmed", waitlist_position: null, email: "a@example.com", message: "" },
      },
    });
    const { user } = renderAt("/events/ev-1");
    await registerAs(user, "A@Example.com");
    expect(await screen.findByText("You're already registered")).toBeInTheDocument();
    expect(screen.getByText(/No second seat was taken/)).toBeInTheDocument();
  });

  it("shows_error_for_closed_registration", async () => {
    mockApi({ ...BASE, "POST /api/events/ev-1/registrations": apiError(409, "registration_closed") });
    const { user } = renderAt("/events/ev-1");
    await registerAs(user, "late@example.com");
    expect(await screen.findByRole("alert")).toHaveTextContent("Registration is closed");
  });

  it("shows_error_for_invalid_email", async () => {
    mockApi({ ...BASE, "POST /api/events/ev-1/registrations": apiError(422, "invalid_email") });
    const { user } = renderAt("/events/ev-1");
    await registerAs(user, "x@site.test");
    expect(await screen.findByRole("alert")).toHaveTextContent("valid email address");
  });

  it("hides_form_for_cancelled_event", async () => {
    mockApi({ ...HEALTH, "GET /api/events/ev-1": { body: { ...EVENT, status: "cancelled" } } });
    renderAt("/events/ev-1");
    expect(await screen.findByText("This event has been cancelled.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your email")).not.toBeInTheDocument();
  });

  it("shows_not_found_error", async () => {
    mockApi({ ...HEALTH, "GET /api/events/nope": apiError(404, "event_not_found") });
    renderAt("/events/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("This event doesn't exist.");
  });
});
