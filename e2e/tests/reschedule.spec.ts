import { expect, test } from "@playwright/test";
import { createEvent, organizerApi, organizerContext, registerViaUi, uid, waitForEmails } from "./helpers";

test("reschedule_emails_every_participant", async ({ browser }) => {
  const api = await organizerApi();
  const title = `Moved ${uid()}`;
  const event = await createEvent(api, { title, capacity: 1 });
  const confirmed = `c-${uid()}@example.com`;
  const waitlisted = `w-${uid()}@example.com`;
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(`/events/${event.id}`);
  await registerViaUi(visitor, confirmed);
  await expect(visitor.getByText("You're in!")).toBeVisible();
  await registerViaUi(visitor, waitlisted);
  await expect(visitor.getByText("The event is full.")).toBeVisible();

  const dashboard = await (await organizerContext(browser, api)).newPage();
  await dashboard.goto(`/admin/events/${event.id}`);
  await expect(dashboard.getByLabel("Live counters")).toBeVisible(); // stats loaded -> modal knows how many get emailed
  const newDate = new Date(Date.now() + 10 * 24 * 3600_000);
  const local = newDate.toISOString().slice(0, 16); // browser runs in UTC (playwright.config)
  await dashboard.getByRole("button", { name: "Reschedule / Edit Event" }).click();
  const dialog = dashboard.getByRole("dialog", { name: "Edit or reschedule event" });
  await dialog.getByLabel("New date and time (your local time)").fill(local);
  await dialog.getByRole("button", { name: "Confirm & Notify 2" }).click(); // 1 registered + 1 waitlisted
  await expect(dashboard.getByText("2 participants notified by email", { exact: false })).toBeVisible();

  for (const who of [confirmed, waitlisted]) {
    const mails = await waitForEmails(who, `New date for ${title}`, 1, 1000);
    expect(mails, who).toHaveLength(1);
  }
  // The public page shows the new date (live stream pushes starts_at); same format as the UI's date tile.
  const dateText = newDate.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  await expect(visitor.getByText(dateText)).toBeVisible();
});
