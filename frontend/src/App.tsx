import { useEffect, useState } from "react";
import { BrowserRouter, Link, Outlet, Route, Routes, useNavigate } from "react-router";
import { api, fetchHealth } from "./api";
import { AdminDashboard } from "./pages/admin/AdminDashboard";
import { AdminEvents } from "./pages/admin/AdminEvents";
import { AdminLogin } from "./pages/admin/AdminLogin";
import { CheckIn } from "./pages/admin/CheckIn";
import { RequireOrganizer } from "./pages/admin/RequireOrganizer";
import { EventPage } from "./pages/EventPage";
import { EventsList } from "./pages/EventsList";
import { TicketPage } from "./pages/TicketPage";

type HealthState = "loading" | "ok" | "db-down" | "unreachable";

const HEALTH_TEXT: Record<HealthState, string> = {
  loading: "Checking backend…",
  ok: "Backend: ok · Database: ok",
  "db-down": "Backend is up, but the database is unavailable.",
  unreachable: "Backend is unreachable.",
};

function HealthFooter() {
  const [health, setHealth] = useState<HealthState>("loading");
  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((h) => setHealth(h.db === "ok" ? "ok" : "db-down"))
      .catch(() => {
        if (!controller.signal.aborted) setHealth("unreachable");
      });
    return () => controller.abort();
  }, []);
  const state = health === "ok" ? "ok" : health === "loading" ? "loading" : "error";
  return (
    <footer>
      <p className="status" role="status" data-state={state}>{HEALTH_TEXT[health]}</p>
    </footer>
  );
}

function AdminLayout() {
  const navigate = useNavigate();
  return (
    <>
      <p className="admin-bar">
        Organizer · <Link to="/admin">Events</Link> ·{" "}
        <button type="button" className="link" onClick={() => api.logout().finally(() => navigate("/admin/login"))}>
          Log out
        </button>
      </p>
      <Outlet />
    </>
  );
}

function Layout() {
  return (
    <>
      <header>
        <Link to="/" className="brand">Event Registration</Link>
        <nav><Link to="/">Events</Link> <Link to="/admin">Organizer</Link></nav>
      </header>
      <main><Outlet /></main>
      <HealthFooter />
    </>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<EventsList />} />
        <Route path="events/:eventId" element={<EventPage />} />
        <Route path="r/:token" element={<TicketPage />} />
        <Route path="admin/login" element={<AdminLogin />} />
        <Route path="admin" element={<RequireOrganizer />}>
          <Route element={<AdminLayout />}>
            <Route index element={<AdminEvents />} />
            <Route path="events/:eventId" element={<AdminDashboard />} />
            <Route path="events/:eventId/checkin" element={<CheckIn />} />
          </Route>
        </Route>
        <Route path="*" element={<p>Page not found. <Link to="/">All events</Link></p>} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
