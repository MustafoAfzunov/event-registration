import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EVENT, mockApi } from "./test/fakes";
import { HEALTH, renderAt } from "./test/render";

describe("App shell", () => {
  it("renders_app_shell", async () => {
    mockApi({ ...HEALTH, "GET /api/events": { body: [] } });
    renderAt("/");
    expect(screen.getByRole("link", { name: "Event Registration" })).toBeInTheDocument();
    expect(await screen.findByText("No upcoming events yet.")).toBeInTheDocument();
  });

  it("calls_api_health_and_shows_ok", async () => {
    const calls = mockApi({ ...HEALTH, "GET /api/events": { body: [] } });
    renderAt("/");
    expect(await screen.findByText("Backend: ok · Database: ok")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/health")).toBe(true);
  });

  it("shows_db_down_on_503", async () => {
    mockApi({ "GET /api/health": { status: 503, body: { status: "degraded", db: "error" } }, "GET /api/events": { body: [] } });
    renderAt("/");
    expect(await screen.findByText(/database is unavailable/)).toBeInTheDocument();
  });

  it("lists_upcoming_events_with_links", async () => {
    mockApi({ ...HEALTH, "GET /api/events": { body: [EVENT] } });
    renderAt("/");
    const link = await screen.findByRole("link", { name: "PyCon Meetup" });
    expect(link).toHaveAttribute("href", "/events/ev-1");
    expect(screen.getByText("2 seats left")).toBeInTheDocument();
  });
});
