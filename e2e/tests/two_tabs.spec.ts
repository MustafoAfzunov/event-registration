import { expect, test } from "@playwright/test";
import {
  createEvent, emailText, markDocument, organizerApi, organizerContext, registerViaUi,
  stillSameDocument, ticketCode, uid, waitForEmails,
} from "./helpers";

test("register_in_tab_a_updates_seat_counter_in_tab_b_live", async ({ browser }) => {
  const api = await organizerApi();
  const event = await createEvent(api, { title: `Live seats ${uid()}`, capacity: 3 });
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();

  await b.goto(`/events/${event.id}`);
  await expect(b.getByText("3 seats left")).toBeVisible();
  await expect(b.getByLabel("Live updates: live")).toBeVisible();
  await markDocument(b);

  await a.goto(`/events/${event.id}`);
  await registerViaUi(a, `a-${uid()}@example.com`);
  await expect(a.getByText("You're in!")).toBeVisible();

  await expect(b.getByText("2 seats left")).toBeVisible();
  expect(await stillSameDocument(b)).toBe(true); // updated without a reload
});

test("checkin_in_tab_b_updates_organizer_counter_in_tab_a_live", async ({ browser }) => {
  const api = await organizerApi();
  const event = await createEvent(api, { title: `Door ${uid()}`, capacity: 5 });
  const guest = `guest-${uid()}@example.com`;
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(`/events/${event.id}`);
  await registerViaUi(visitor, guest);
  await expect(visitor.getByText("You're in!")).toBeVisible();
  const [ticket] = await waitForEmails(guest, "Your ticket");
  const code = ticketCode(await emailText(ticket!));

  // Tab A: organizer dashboard. Tab B: door staff (separate browser context, same login).
  const dashboard = await (await organizerContext(browser, api)).newPage();
  await dashboard.goto(`/admin/events/${event.id}`);
  const checkedIn = dashboard.getByLabel("Live counters").getByLabel("Checked in");
  await expect(checkedIn).toHaveText("0");
  await expect(dashboard.getByLabel("Live updates: live")).toBeVisible();
  await markDocument(dashboard);

  const door = await (await organizerContext(browser, api)).newPage();
  await door.goto(`/admin/events/${event.id}/checkin`);
  await door.getByLabel("Ticket code").fill(code.toLowerCase().replace("-", " "));
  await door.keyboard.press("Enter");
  await expect(door.getByRole("alert")).toContainText("Welcome!");

  await expect(checkedIn).toHaveText("1");
  await expect(dashboard.getByLabel("Live counters").getByLabel("Not arrived yet")).toHaveText("0");
  expect(await stillSameDocument(dashboard)).toBe(true);
});

test("two_participants_race_for_last_seat_one_confirmed_one_waitlisted", async ({ browser }) => {
  const api = await organizerApi();
  for (let round = 0; round < 3; round++) {
    const event = await createEvent(api, { title: `Last seat ${round} ${uid()}`, capacity: 1 });
    const [p1, p2] = await Promise.all([
      browser.newContext().then((c) => c.newPage()),
      browser.newContext().then((c) => c.newPage()),
    ]);
    await Promise.all([p1.goto(`/events/${event.id}`), p2.goto(`/events/${event.id}`)]);
    await p1.getByLabel("Your email").fill(`r1-${uid()}@example.com`);
    await p2.getByLabel("Your email").fill(`r2-${uid()}@example.com`);

    // Both press "Register" at the same moment.
    await Promise.all([
      p1.getByRole("button", { name: "Register" }).click(),
      p2.getByRole("button", { name: "Register" }).click(),
    ]);
    const outcome = async (p: typeof p1) => {
      await expect(p.getByText(/You're in!|The event is full\./)).toBeVisible();
      return (await p.getByText("You're in!").count()) ? "confirmed" : "waitlisted";
    };
    expect([await outcome(p1), await outcome(p2)].sort()).toEqual(["confirmed", "waitlisted"]);

    const stats = await (await api.get(`/api/admin/events/${event.id}/stats`)).json();
    expect([stats.registered, stats.waitlisted, stats.seats_left]).toEqual([1, 1, 0]);
  }
});
