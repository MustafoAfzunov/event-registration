import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { EVENT, apiError, installEventSource, mockApi } from "../test/fakes";
import { HEALTH, renderAt } from "../test/render";

const FUTURE = "2099-11-01T15:00:00Z";
const PAST = "2001-11-01T15:00:00Z";
const eventRoute = (over: Record<string, unknown>) => ({ ...HEALTH, "GET /api/events/ev-1": { body: { ...EVENT, ...over } } });

describe("EventPage availability states", () => {
  beforeEach(installEventSource);

  it("shows_available_state_with_registered_count", async () => {
    mockApi(eventRoute({ capacity: 10, seats_left: 8 }));
    renderAt("/events/ev-1");
    expect(await screen.findByText("Seats available")).toBeInTheDocument();
    expect(screen.getByText("2 / 10 registered")).toBeInTheDocument();
    expect(screen.getByText("20% full")).toBeInTheDocument();
    expect(screen.getByText("Registration open")).toBeInTheDocument();
  });

  it("shows_high_demand_when_80_percent_taken", async () => {
    mockApi(eventRoute({ capacity: 10, seats_left: 2 }));
    renderAt("/events/ev-1");
    expect(await screen.findByText("High demand")).toBeInTheDocument();
    expect(screen.getByText("2 seats left")).toBeInTheDocument();
    expect(screen.getByText("80% full")).toBeInTheDocument();
  });

  it("shows_waitlist_box_and_amber_button_when_full", async () => {
    mockApi(eventRoute({ capacity: 3, seats_left: 0, waitlist_count: 4 }));
    renderAt("/events/ev-1");
    expect(await screen.findByText("Sold out · waitlist open")).toBeInTheDocument();
    expect(screen.getByText("Full · 4 people on the waitlist")).toBeInTheDocument();
    expect(screen.getByText("Join the waitlist")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join waitlist" })).toBeInTheDocument();
    expect(screen.getByText("Full · waitlist open")).toBeInTheDocument(); // hero chip
  });

  it("shows_closed_notice_and_no_form_after_start", async () => {
    mockApi(eventRoute({ starts_at: PAST }));
    renderAt("/events/ev-1");
    expect(await screen.findByText("Registration is closed: the event has started.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your email")).not.toBeInTheDocument();
    expect(screen.getByText("Started")).toBeInTheDocument();
  });

  it("shows_description_or_an_empty_state", async () => {
    mockApi(eventRoute({ description: "" }));
    renderAt("/events/ev-1");
    expect(await screen.findByText("The organizer hasn't added a description yet.")).toBeInTheDocument();
  });

  it("shows_capacity_tile_with_waiting_count_from_the_api", async () => {
    mockApi(eventRoute({ capacity: 5, seats_left: 3, waitlist_count: 0 }));
    renderAt("/events/ev-1");
    expect(await screen.findByText("5 seats")).toBeInTheDocument();
    expect(screen.getByText("2 registered · 0 waiting")).toBeInTheDocument();
  });
});

describe("TicketPage presentation", () => {
  const reg = (over: Record<string, unknown>, eventOver: Record<string, unknown> = {}) => ({
    ...HEALTH,
    "GET /api/registrations/tok": {
      body: { event: { ...EVENT, ...eventOver }, email: "a@example.com", status: "confirmed", ticket_code: "ABCD-EFGH", waitlist_position: null, checked_in_at: null, ...over },
    },
  });

  it("shows_countdown_to_the_event_start", async () => {
    mockApi(reg({}, { starts_at: FUTURE }));
    renderAt("/r/tok");
    const timer = await screen.findByRole("timer", { name: "Time until the event starts" });
    expect(within(timer).getByText("Days")).toBeInTheDocument();
    expect(within(timer).getByText("Hours")).toBeInTheDocument();
    expect(within(timer).getByText("Minutes")).toBeInTheDocument();
  });

  it("shows_started_instead_of_countdown_after_the_start", async () => {
    mockApi(reg({}, { starts_at: PAST }));
    renderAt("/r/tok");
    expect(await screen.findByText("The event has started.")).toBeInTheDocument();
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
    expect(screen.getByText(/can no longer be changed/)).toBeInTheDocument();
  });

  it("shows_event_cancelled_banner_and_blocks_cancel", async () => {
    mockApi(reg({}, { status: "cancelled" }));
    renderAt("/r/tok");
    expect(await screen.findByText("This event has been cancelled by the organizer.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel my registration/i })).not.toBeInTheDocument();
  });

  it("shows_attendee_email_and_ticket_code_on_the_pass", async () => {
    mockApi(reg({}));
    renderAt("/r/tok");
    expect(await screen.findByLabelText("Attendee")).toHaveTextContent("a@example.com");
    expect(screen.getByLabelText("Ticket code")).toHaveTextContent("ABCD-EFGH");
    expect(screen.getByText("Confirmed & valid")).toBeInTheDocument();
  });

  it("shows_no_ticket_for_waitlisted_and_cancelled", async () => {
    mockApi(reg({ status: "waitlisted", ticket_code: null, waitlist_position: 4 }));
    renderAt("/r/tok");
    expect(await screen.findByText(/No ticket yet/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Ticket code")).not.toBeInTheDocument();
  });
});

describe("EventsList states", () => {
  it("shows_a_full_event_as_waiting_count", async () => {
    mockApi({ ...HEALTH, "GET /api/events": { body: [{ ...EVENT, seats_left: 0, waitlist_count: 3 }] } });
    renderAt("/");
    expect(await screen.findByText("Full · 3 waiting")).toBeInTheDocument();
  });

  it("shows_the_error_state", async () => {
    mockApi({ ...HEALTH, "GET /api/events": apiError(500, "internal_error") });
    renderAt("/");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("shows_loading_before_the_list_arrives", async () => {
    mockApi({ ...HEALTH, "GET /api/events": () => new Promise(() => {}) as never });
    renderAt("/");
    expect(await screen.findByText("Loading events…")).toBeInTheDocument();
  });
});

describe("Navigation", () => {
  it("has_no_my_tickets_and_no_search_or_profile_from_the_mockups", async () => {
    mockApi({ ...HEALTH, "GET /api/events": { body: [] } });
    renderAt("/");
    await screen.findByText("No upcoming events yet.");
    expect(screen.queryByText("My Tickets")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/search events/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /notifications/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/EventPulse/)).not.toBeInTheDocument();
    for (const nav of screen.getAllByRole("navigation", { name: /^Main/ })) {
      expect(within(nav).getByRole("link", { name: "Explore Events" })).toHaveAttribute("href", "/");
      expect(within(nav).getByRole("link", { name: "Organizer Studio" })).toHaveAttribute("href", "/admin");
      expect(within(nav).queryByRole("link", { name: "Check-In Terminal" })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Log out" })).not.toBeInTheDocument();
  });

  it("shows_check_in_terminal_and_logout_only_inside_an_event_in_the_organizer_area", async () => {
    installEventSource();
    mockApi({
      ...HEALTH,
      "GET /api/admin/me": { body: { role: "organizer" } },
      "GET /api/events/ev-1": { body: EVENT },
      "GET /api/admin/events/ev-1/stats": { body: { capacity: 3, confirmed: 0, checked_in: 0, registered: 0, waitlisted: 0, cancelled: 0, seats_left: 3, emails: { pending: 0, sending: 0, sent: 0, failed: 0, skipped: 0 } } },
      "GET /api/admin/events/ev-1/registrations": { body: [] },
    });
    renderAt("/admin/events/ev-1");
    await screen.findByRole("heading", { name: "PyCon Meetup" });
    for (const nav of screen.getAllByRole("navigation", { name: /^Main/ })) {
      expect(within(nav).getByRole("link", { name: "Check-In Terminal" })).toHaveAttribute("href", "/admin/events/ev-1/checkin");
    }
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });
});
