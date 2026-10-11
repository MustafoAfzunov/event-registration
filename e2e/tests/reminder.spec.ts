import { expect, test } from "@playwright/test";
import { createEvent, organizerApi, registerViaUi, uid, waitForEmails } from "./helpers";

// The isolated E2E stack runs the worker with SCHEDULER_TICK_SECONDS=2 (scripts/e2e.sh).
test("event_23h_ahead_gets_exactly_one_reminder", async ({ page }) => {
  const api = await organizerApi();
  const title = `Soon ${uid()}`;
  const event = await createEvent(api, { title, capacity: 1, startsInHours: 23 });
  const confirmed = `soon-${uid()}@example.com`;
  const waitlisted = `late-${uid()}@example.com`;
  await page.goto(`/events/${event.id}`);
  await registerViaUi(page, confirmed);
  await expect(page.getByText("You're in!")).toBeVisible();
  await registerViaUi(page, waitlisted);
  await expect(page.getByText("The event is full.")).toBeVisible();

  // >= 3 more scheduler ticks after the first reminder must not produce a second one.
  expect(await waitForEmails(confirmed, `Reminder: ${title}`, 1, 7000)).toHaveLength(1);
  expect(await waitForEmails(waitlisted, "Reminder:", 0, 0)).toHaveLength(0);
});
