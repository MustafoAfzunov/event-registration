// The one place that talks to the backend (docs/API.md). Relative /api URLs: nginx (compose)
// or the Vite dev proxy forwards them, so the browser sees a single origin and the organizer
// cookie just works.

export type Health = { status: "ok" | "degraded"; db: "ok" | "error" };
export type EventStatus = "scheduled" | "cancelled";
export type RegistrationStatus = "confirmed" | "waitlisted" | "cancelled" | "checked_in";

export type PublicEvent = {
  id: string;
  title: string;
  description: string;
  starts_at: string;
  capacity: number;
  seats_left: number;
  waitlist_count: number;
  status: EventStatus;
};

export type Availability = {
  event_id: string;
  status: EventStatus;
  starts_at: string;
  capacity: number;
  seats_left: number;
  waitlist_count: number;
};

export type RegisterResult = {
  created: boolean;
  status: RegistrationStatus;
  waitlist_position: number | null;
  email: string;
  message: string;
};

export type MyRegistration = {
  event: PublicEvent;
  email: string;
  status: RegistrationStatus;
  ticket_code: string | null;
  waitlist_position: number | null;
  checked_in_at: string | null;
};

export type Stats = {
  capacity: number;
  confirmed: number;
  checked_in: number;
  registered: number;
  waitlisted: number;
  cancelled: number;
  seats_left: number;
  emails: { pending: number; sending: number; sent: number; failed: number; skipped: number };
};

export type AdminRegistration = {
  id: string;
  email: string;
  status: RegistrationStatus;
  ticket_code: string;
  waitlist_position: number | null;
  created_at: string;
  checked_in_at: string | null;
};

export type CheckInResult = { result: "checked_in"; email: string; checked_in_at: string };
export type EventInput = { title: string; description: string; starts_at: string; capacity: number };
export type EventPatch = Partial<Pick<EventInput, "title" | "description" | "capacity">>;
export type NotifyResult = { event: PublicEvent; notified: number; changed: boolean };

/** Every failure, including network errors, as one type with the API's stable `code`. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers:
        body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the server.");
  }
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed (${response.status})`,
      error?.details ?? {},
    );
  }
  return data as T;
}

/** GET /api/health. Resolves for 200 and 503 (both carry a body); rejects if unreachable. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal, headers: { Accept: "application/json" } });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Unexpected status ${response.status}`);
  }
  return (await response.json()) as Health;
}

const enc = encodeURIComponent;

export const api = {
  // public
  listEvents: () => request<PublicEvent[]>("GET", "/api/events"),
  getEvent: (id: string) => request<PublicEvent>("GET", `/api/events/${enc(id)}`),
  register: (id: string, email: string) =>
    request<RegisterResult>("POST", `/api/events/${enc(id)}/registrations`, { email }),
  // participant (capability link)
  getRegistration: (token: string) => request<MyRegistration>("GET", `/api/registrations/${enc(token)}`),
  cancelRegistration: (token: string) =>
    request<{ status: RegistrationStatus }>("POST", `/api/registrations/${enc(token)}/cancel`),
  // organizer
  login: (password: string) => request<void>("POST", "/api/admin/login", { password }),
  logout: () => request<void>("POST", "/api/admin/logout"),
  me: () => request<{ role: string }>("GET", "/api/admin/me"),
  adminEvents: () => request<PublicEvent[]>("GET", "/api/admin/events"),
  createEvent: (input: EventInput) => request<PublicEvent>("POST", "/api/admin/events", input),
  updateEvent: (id: string, patch: EventPatch) =>
    request<PublicEvent & { promoted_count: number }>("PATCH", `/api/admin/events/${enc(id)}`, patch),
  reschedule: (id: string, startsAt: string) =>
    request<NotifyResult>("POST", `/api/admin/events/${enc(id)}/reschedule`, { starts_at: startsAt }),
  cancelEvent: (id: string) => request<NotifyResult>("POST", `/api/admin/events/${enc(id)}/cancel`),
  stats: (id: string) => request<Stats>("GET", `/api/admin/events/${enc(id)}/stats`),
  registrations: (id: string, status?: RegistrationStatus) =>
    request<AdminRegistration[]>(
      "GET",
      `/api/admin/events/${enc(id)}/registrations${status ? `?status=${status}` : ""}`,
    ),
  checkIn: (id: string, code: string) =>
    request<CheckInResult>("POST", `/api/admin/events/${enc(id)}/checkin`, { code }),
};

export const streams = {
  availability: (id: string) => `/api/events/${enc(id)}/stream`,
  stats: (id: string) => `/api/admin/events/${enc(id)}/stream`,
};
