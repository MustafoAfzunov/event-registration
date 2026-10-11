import { request, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

export const BASE_URL = process.env.BASE_URL ?? "http://frontend";
export const MAILPIT = process.env.MAILPIT_URL ?? "http://mailpit:8025";
const PASSWORD = process.env.ORGANIZER_PASSWORD ?? "organizer-dev-password";

/** Unique suffix so tests never depend on each other's data or mailbox. */
export const uid = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** API client logged in as organizer (also the source of the browser's organizer cookie). */
export async function organizerApi(): Promise<APIRequestContext> {
  const api = await request.newContext({ baseURL: BASE_URL });
  const r = await api.post("/api/admin/login", { data: { password: PASSWORD } });
  if (r.status() !== 204) throw new Error(`organizer login failed: ${r.status()}`);
  return api;
}

export async function organizerContext(browser: Browser, api: APIRequestContext): Promise<BrowserContext> {
  return browser.newContext({ storageState: await api.storageState() });
}

export async function createEvent(
  api: APIRequestContext,
  opts: { title: string; capacity: number; startsInHours?: number },
): Promise<{ id: string; title: string; starts_at: string }> {
  const startsAt = new Date(Date.now() + (opts.startsInHours ?? 24 * 7) * 3600_000);
  startsAt.setUTCSeconds(0, 0);
  const r = await api.post("/api/admin/events", {
    data: { title: opts.title, description: "E2E", starts_at: startsAt.toISOString(), capacity: opts.capacity },
  });
  if (r.status() !== 201) throw new Error(`create event: ${r.status()} ${await r.text()}`);
  return r.json();
}

export async function registerViaUi(page: Page, email: string): Promise<void> {
  await page.getByLabel("Your email").fill(email);
  await page.getByRole("button", { name: /^(Register|Join waitlist)$/ }).click();
}

/** Marks the page; `assertNoReload` later proves the same document is still loaded. */
export async function markDocument(page: Page): Promise<void> {
  await page.evaluate(() => ((window as unknown as { __e2eMark: number }).__e2eMark = 42));
}
export async function stillSameDocument(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __e2eMark?: number }).__e2eMark === 42);
}

// ---------------------------------------------------------------- Mailpit
type Message = { ID: string; Subject: string; To: { Address: string }[] };

async function mailpit(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: MAILPIT });
}

export async function emails(to: string, subjectPart = ""): Promise<Message[]> {
  const mp = await mailpit();
  const r = await mp.get("/api/v1/search", { params: { query: `to:"${to}"`, limit: "100" } });
  const body = (await r.json()) as { messages: Message[] };
  await mp.dispose();
  return body.messages.filter((m) => m.Subject.includes(subjectPart));
}

/** Wait until `count` matching emails exist, then wait `settleMs` and return them all
 * (so an unexpected duplicate would be visible to the caller's assertion). */
export async function waitForEmails(to: string, subjectPart: string, count = 1, settleMs = 1500): Promise<Message[]> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if ((await emails(to, subjectPart)).length >= count) break;
    await new Promise((r) => setTimeout(r, 300));
  }
  await new Promise((r) => setTimeout(r, settleMs));
  return emails(to, subjectPart);
}

export async function emailText(message: Message): Promise<string> {
  const mp = await mailpit();
  const r = await mp.get(`/api/v1/message/${message.ID}`);
  const body = (await r.json()) as { Text: string };
  await mp.dispose();
  return body.Text;
}

export function ticketCode(text: string): string {
  const m = /Your ticket code: ([0-9A-Z]{4}-[0-9A-Z]{4})/.exec(text);
  if (!m?.[1]) throw new Error(`no ticket code in email:\n${text}`);
  return m[1];
}

/** Path of the manage link (/r/<token>); host-independent, opened against BASE_URL. */
export function managePath(text: string): string {
  const m = /\/r\/[A-Za-z0-9_-]+/.exec(text);
  if (!m) throw new Error(`no manage link in email:\n${text}`);
  return m[0];
}
