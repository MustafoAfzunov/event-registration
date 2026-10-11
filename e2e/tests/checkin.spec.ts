import { expect, test } from "@playwright/test";
import { createEvent, emailText, organizerApi, organizerContext, registerViaUi, ticketCode, uid, waitForEmails } from "./helpers";

test("second_checkin_rejected", async ({ browser, page }) => {
  const api = await organizerApi();
  const event = await createEvent(api, { title: `Once ${uid()}`, capacity: 5 });
  const email = `once-${uid()}@example.com`;
  await page.goto(`/events/${event.id}`);
  await registerViaUi(page, email);
  const [mail] = await waitForEmails(email, "Your ticket");
  const code = ticketCode(await emailText(mail!));

  const door = await (await organizerContext(browser, api)).newPage();
  await door.goto(`/admin/events/${event.id}/checkin`);
  const input = door.getByLabel("Ticket code");
  await input.fill(code);
  await input.press("Enter");
  await expect(door.getByRole("alert")).toContainText("Welcome!");
  await expect(input).toHaveValue("");

  await input.fill(code);
  await input.press("Enter");
  await expect(door.getByRole("alert")).toContainText("Already used");
  await expect(door.getByLabel("Arrived")).toHaveText("1 / 1 arrived");
  const stats = await (await api.get(`/api/admin/events/${event.id}/stats`)).json();
  expect(stats.checked_in).toBe(1);
});
