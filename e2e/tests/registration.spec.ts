import { expect, test } from "@playwright/test";
import { createEvent, emailText, managePath, organizerApi, registerViaUi, ticketCode, uid, waitForEmails } from "./helpers";

test("register_receive_ticket_email_and_view_ticket", async ({ page }) => {
  const api = await organizerApi();
  const event = await createEvent(api, { title: `Ticket ${uid()}`, capacity: 5 });
  const email = `t-${uid()}@example.com`;

  await page.goto(`/events/${event.id}`);
  await registerViaUi(page, email);
  await expect(page.getByText(`Your ticket is on its way to ${email}`)).toBeVisible();

  const [mail] = await waitForEmails(email, "Your ticket");
  const text = await emailText(mail!);
  await page.goto(managePath(text));
  await expect(page.getByLabel("Ticket code")).toHaveText(ticketCode(text));
  await expect(page.getByText(`Registration for ${email}`)).toBeVisible();
});

test("duplicate_registration_no_second_seat_no_second_email", async ({ browser }) => {
  const api = await organizerApi();
  const event = await createEvent(api, { title: `Dup ${uid()}`, capacity: 5 });
  const email = `dup-${uid()}@example.com`;
  const first = await (await browser.newContext()).newPage();
  const second = await (await browser.newContext()).newPage();

  await first.goto(`/events/${event.id}`);
  await registerViaUi(first, email);
  await expect(first.getByText("You're in!")).toBeVisible();
  await second.goto(`/events/${event.id}`);
  await registerViaUi(second, `  ${email.toUpperCase()} `);
  await expect(second.getByText("You're already registered")).toBeVisible();

  const stats = await (await api.get(`/api/admin/events/${event.id}/stats`)).json();
  expect(stats.registered).toBe(1);
  expect(await waitForEmails(email, "", 1, 3000)).toHaveLength(1);
});
