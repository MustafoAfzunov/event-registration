import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

function stubFetch(impl: () => Promise<Response>) {
  const fetchMock = vi.fn(impl);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const json = (body: unknown, status: number) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("App", () => {
  it("renders_app_shell", () => {
    stubFetch(() => new Promise(() => {})); // never resolves: stays in loading state
    render(<App />);
    expect(screen.getByRole("heading", { name: "Event Registration" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Checking backend");
  });

  it("calls_api_health_and_shows_ok", async () => {
    const fetchMock = stubFetch(() => json({ status: "ok", db: "ok" }, 200));
    render(<App />);
    expect(await screen.findByText("Backend: ok · Database: ok")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("shows_db_down_on_503", async () => {
    stubFetch(() => json({ status: "degraded", db: "error" }, 503));
    render(<App />);
    expect(await screen.findByText(/database is unavailable/)).toBeInTheDocument();
  });

  it("shows_unreachable_on_network_error", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    render(<App />);
    expect(await screen.findByText("Backend is unreachable.")).toBeInTheDocument();
  });
});
