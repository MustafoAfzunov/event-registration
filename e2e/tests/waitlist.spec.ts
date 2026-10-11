import { expect, test } from "@playwright/test";
import { createEvent, emailText, managePath, organizerApi, registerViaUi, ticketCode, uid, waitForEmails } from "./helpers";

test("full_event_waitlists_then_promotes_on_cancel_with_email", async ({ browser }) => {
  const api = await organizerApi();
  const event = await createEvent(api, { title: `Waitlist ${uid()}`, capacity: 1 });
  const holder = `holder-${uid()}@example.com`;
  const waiter = `waiter-${uid()}@example.com`;
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();

  await a.goto(`/events/${event.id}`);
  await registerViaUi(a, holder);
  await expect(a.getByText("You're in!")).toBeVisible();
  await b.goto(`/events/${event.id}`);
  await registerViaUi(b, waiter);
  await expect(b.getByText("You're #1 on the waitlist", { exact: false })).toBeVisible();
  const [notice] = await waitForEmails(waiter, "waitlist");
  expect(notice).toBeTruthy();

  // Holder cancels from the link in their ticket email (real browser confirm dialog).
  const [ticket] = await waitForEmails(holder, "Your ticket");
  await a.goto(managePath(await emailText(ticket!)));
  a.once("dialog", (d) => d.accept());
  await a.getByRole("button", { name: "Cancel my registration" }).click();
  await expect(a.getByText("This registration is cancelled.")).toBeVisible();

  // The waitlisted person automatically gets the seat AND exactly one email with a ticket.
  const promoted = await waitForEmails(waiter, "A seat opened up", 1, 3000);
  expect(promoted).toHaveLength(1);
  const text = await emailText(promoted[0]!);
  await b.goto(managePath(text));
  await expect(b.getByLabel("Ticket code")).toHaveText(ticketCode(text));
});
