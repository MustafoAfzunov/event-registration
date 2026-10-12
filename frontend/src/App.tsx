import { useEffect, useState } from "react";
import { BrowserRouter, Link, NavLink, Outlet, Route, Routes, useMatch, useNavigate } from "react-router";
import { api, fetchHealth } from "./api";
import { Icon } from "./components/Icon";
import { btnSecondary, pageX } from "./components/styles";
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

const HEALTH_BOX: Record<HealthState, string> = {
  loading: "bg-surface-container-high text-on-surface-variant",
  ok: "bg-secondary-container text-on-secondary-container",
  "db-down": "bg-error-container text-on-error-container",
  unreachable: "bg-error-container text-on-error-container",
};

function HealthStatus() {
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
    <p role="status" data-state={state} className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full font-label-sm text-label-sm ${HEALTH_BOX[health]}`}>
      <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-current" />
      {HEALTH_TEXT[health]}
    </p>
  );
}

function BrandMark({ small = false }: { small?: boolean }) {
  return (
    <span className={`${small ? "w-6 h-6" : "w-8 h-8"} rounded-lg bg-primary text-on-primary flex items-center justify-center shrink-0`}>
      <Icon name="confirmation_number" filled className={small ? "text-[16px]" : "text-[20px]"} />
    </span>
  );
}

const navActive = "text-primary font-bold font-label-lg text-label-lg transition-colors";
const navIdle = "font-label-lg text-label-lg text-on-surface-variant hover:text-on-surface transition-colors";
const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? navActive : navIdle);

function Header() {
  const navigate = useNavigate();
  const adminMatch = useMatch("/admin/*");
  const loginMatch = useMatch("/admin/login");
  const inAdmin = adminMatch !== null && loginMatch === null;
  const eventId = useMatch("/admin/events/:eventId/*")?.params.eventId;
  // "My Tickets" from the design is omitted: participants have no accounts, they use the emailed link.
  // The check-in terminal needs an event, so it only appears inside an event's organizer pages.
  const links = (
    <>
      <NavLink to="/" end className={navClass}>Explore Events</NavLink>
      <NavLink to="/admin" className={navClass}>Organizer Studio</NavLink>
      {eventId && <NavLink to={`/admin/events/${eventId}/checkin`} className={navClass}>Check-In Terminal</NavLink>}
    </>
  );
  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-surface/90 backdrop-blur-xl border-b border-outline-variant">
      <div className={`h-16 w-full ${pageX} flex items-center justify-between gap-gutter`}>
        <div className="flex items-center gap-space-lg min-w-0">
          <Link to="/" className="flex items-center gap-space-sm min-w-0">
            <BrandMark />
            <span className="font-headline-sm text-headline-sm text-on-surface truncate">Event Registration</span>
          </Link>
          <nav aria-label="Main" className="hidden lg:flex items-center gap-space-lg">{links}</nav>
        </div>
        {inAdmin && (
          <button
            type="button"
            className={`${btnSecondary} !py-1.5`}
            onClick={() => api.logout().finally(() => navigate("/admin/login"))}
          >
            <Icon name="logout" className="text-[18px]" />
            Log out
          </button>
        )}
      </div>
      {/* The design hides its nav below lg and has no replacement; phones get a compact scrolling row. */}
      <nav aria-label="Main (mobile)" className={`lg:hidden h-10 ${pageX} flex items-center gap-space-lg overflow-x-auto whitespace-nowrap border-t border-outline-variant/50`}>
        {links}
      </nav>
    </header>
  );
}

function Footer() {
  return (
    <footer className="w-full bg-surface-container-low border-t border-outline-variant py-space-xl">
      <div className={`w-full ${pageX} flex flex-col md:flex-row items-center justify-between gap-space-md`}>
        <div className="flex items-center gap-space-sm">
          <BrandMark small />
          <span className="font-label-lg text-label-lg text-on-surface">Event Registration</span>
        </div>
        <HealthStatus />
      </div>
    </footer>
  );
}

function Layout() {
  return (
    <>
      <Header />
      <main className="w-full pt-[6.5rem] lg:pt-16 bg-surface min-h-screen">
        <Outlet />
      </main>
      <Footer />
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
          <Route index element={<AdminEvents />} />
          <Route path="events/:eventId" element={<AdminDashboard />} />
          <Route path="events/:eventId/checkin" element={<CheckIn />} />
        </Route>
        <Route
          path="*"
          element={
            <div className="w-full max-w-7xl mx-auto px-margin-mobile md:px-margin py-space-xl">
              <p className="font-body-lg text-body-lg text-on-surface-variant">
                Page not found. <Link to="/" className="text-primary hover:underline">All events</Link>
              </p>
            </div>
          }
        />
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
