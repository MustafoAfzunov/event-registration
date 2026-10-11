import { act } from "@testing-library/react";
import { vi } from "vitest";

/** Minimal stand-in for the browser's EventSource (jsdom has none). */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Set<(e: MessageEvent<string>) => void>>();

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (e: MessageEvent<string>) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(fn);
  }

  removeEventListener(type: string, fn: (e: MessageEvent<string>) => void) {
    this.listeners.get(type)?.delete(fn);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  /** Server sends `event: <type>` with JSON data. */
  emit(type: string, data: unknown) {
    act(() => {
      this.readyState = FakeEventSource.OPEN;
      for (const fn of this.listeners.get(type) ?? []) {
        fn(new MessageEvent(type, { data: JSON.stringify(data) }));
      }
    });
  }

  open() {
    act(() => {
      this.readyState = FakeEventSource.OPEN;
      this.onopen?.();
    });
  }

  /** Connection dropped; `fatal` = server refused, browser won't retry. */
  fail(fatal = false) {
    act(() => {
      this.readyState = fatal ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
      this.onerror?.();
    });
  }

  static latest(urlPart: string): FakeEventSource {
    const found = [...FakeEventSource.instances].reverse().find((s) => s.url.includes(urlPart));
    if (!found) throw new Error(`no EventSource for ${urlPart}`);
    return found;
  }
}

export function installEventSource() {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
}

type Reply = { status?: number; body?: unknown };
type Handler = Reply | ((body: unknown) => Reply | Promise<Reply>);
export type Call = { method: string; path: string; body: unknown };

/** Route table for fetch: keys are "METHOD /path" (query string optional in the key). */
export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const url = new URL(String(input), "http://localhost");
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, path: url.pathname + url.search, body });
      const handler = routes[`${method} ${url.pathname}${url.search}`] ?? routes[`${method} ${url.pathname}`];
      if (!handler) {
        return new Response(JSON.stringify({ error: { code: "not_mocked", message: `${method} ${url}`, details: {} } }), { status: 500 });
      }
      const reply = typeof handler === "function" ? await handler(body) : handler;
      const status = reply.status ?? 200;
      return new Response(status === 204 ? null : JSON.stringify(reply.body ?? {}), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

export const apiError = (status: number, code: string, details: Record<string, unknown> = {}): Reply => ({
  status,
  body: { error: { code, message: code, details } },
});

export const EVENT = {
  id: "ev-1",
  title: "PyCon Meetup",
  description: "Talks and pizza",
  starts_at: "2099-11-01T15:00:00Z",
  capacity: 3,
  seats_left: 2,
  waitlist_count: 0,
  status: "scheduled" as const,
};

export const STATS = {
  capacity: 3,
  confirmed: 1,
  checked_in: 0,
  registered: 1,
  waitlisted: 0,
  cancelled: 0,
  seats_left: 2,
  emails: { pending: 0, sending: 0, sent: 1, failed: 0, skipped: 0 },
};
