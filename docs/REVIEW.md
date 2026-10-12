# Phase 9 Review: findings

**Reviewer stance:** skeptical, as if seeing the repo for the first time. Sources: the code, `docs/TEST_PLAN.md`, README / CLAUDE.md claims, and **probes against the running stack**. Every finding marked *verified* was reproduced, not inferred. Severity:

- **HIGH:** can lose, duplicate or corrupt seats or emails, or breaks an explicit security claim of the project.
- **MEDIUM:** a real weakness with a narrower trigger, or a claim/test gap a reviewer would flag.
- **LOW:** hardening, UX or test-robustness.

Each finding has a proposed test that reproduces it. **Status** is updated as fixes land.

| ID | Sev | Title | Status |
|---|---|---|---|
| H1 | HIGH | One unsendable email wedges its whole outbox batch forever | **fixed**: tests seen red first, then green |
| H2 | HIGH | Manage tokens (capability links) written to backend and nginx access logs | **fixed**: tests seen red first, then green |
| M1 | MEDIUM | CSRF on body-less organizer POSTs from same-site origins | open |
| M2 | MEDIUM | Logout doesn't revoke the session; open organizer streams keep running | open |
| M3 | MEDIUM | Dev secrets and insecure cookie are silent defaults even with `APP_ENV=production` | open |
| M4 | MEDIUM | "Your local time" code paths are only ever tested in UTC | open |
| M5 | MEDIUM | README says only Docker + make are needed; scripts need bash, curl and GNU `date` | README corrected; scripts unchanged |
| L1 | LOW | Emails show UTC while the UI shows local time | open |
| L2 | LOW | Non-reminder emails aren't re-validated at send time | open |
| L3 | LOW | SSE: subscriber cleanup on real disconnect not verified end-to-end; no connection cap | open |
| L4 | LOW | Timing-sensitive tests that could flake on a slow machine | open |
| L5 | LOW | `seats_taken == number of seat holders` is maintained by code, not enforced by the DB | open |
| L6 | LOW | `docker compose up --build` without make is claimed in the README but never tested | checked by hand from a clean clone (phase 10); still no automated test |
| L7 | LOW | One snapshot query per open stream per change (N viewers = N queries) | open |
| U1 | MEDIUM | Live updates never recover after the backend restarts (the browser gives up and the hook doesn't reopen the stream) | open, found after phase 7b by manual browser testing |
| U2 | LOW | A cancelled event's page still shows "Cancel anytime…" under the form | open |
| U3 | LOW | `/events/not-a-uuid` shows a validation message instead of "not found" | open |
| U4 | LOW | No favicon; the SPA fallback answers `/favicon.ico` with `index.html` | open |

What I looked for and did **not** find: overbooking or duplicate seats under any interleaving I could construct (event lock + CHECK + partial unique index, all mutation-tested), lock-order inversions, SQL injection, XSS (React escaping; emails are plain text), open redirect after login (`next` must start with `/admin`), and non-idempotent enqueue (every email kind has a deterministic dedupe key).

---

## H1: One unsendable email wedges its whole outbox batch forever (HIGH, verified)

**Where:** `app/emails/dispatcher.py::deliver`, where `build_message(...)` runs **outside** the `try` that handles SMTP errors. `app/schemas.py::Title` allows CR/LF.

**Trigger:** the organizer creates an event whose title contains a line break, a pasted string, or a deliberate `"Line\nBcc: x@y"` (the API accepts it: verified, 201). Every email for that event has `Subject: … {title}`. Python's `EmailMessage` rejects header values with CR/LF (`ValueError`, verified). That is good, because it blocks header injection, but the error escapes `deliver()`:

1. `run_once()` aborts mid-batch. The poison row **and every other row claimed in the same batch** stay in `sending`.
2. After the lease, the lowest ids, which are the same batch, are claimed together again, and the poison row aborts them again.
3. `attempts` grows past `OUTBOX_MAX_ATTEMPTS` but the row never becomes `failed`, because `mark_failed_attempt` is never reached.

**Probe result** (4 lease cycles, 1 poison + 3 normal rows): all 4 rows stuck in `sending` with `attempts=4`, and **0 emails delivered**. Innocent participants, possibly of *other* events, never get their tickets, and nothing shows as failed.

**Proposed tests:**
- `test_review.py::test_review_h1_unsendable_email_fails_alone_and_others_are_delivered`: one outbox row with a CR/LF subject plus three normal registrations. The dispatcher runs, the clock moves past leases, and the three normal emails arrive in Mailpit exactly once, while the poison row is `failed` after 1 attempt with the reason recorded.
- `test_review.py::test_review_h1_title_with_line_break_rejected`: create or patch an event with a CR/LF or other control character in the title gives 422.

**Status: fixed.** `test_review_h1_*` were red before the fix (ValueError escaped `run_once`; the API accepted the titles). A mutation removing the per-row isolation makes `test_review_h1_unexpected_error_in_one_row_does_not_block_batch` fail again.

**Fix:**
1. Building or preparing a message is a *permanent* failure, so the row goes straight to `failed` with the reason.
2. `run_once` isolates rows, so one row's unexpected exception can never abort its batch-mates.
3. Titles reject control characters at the API.

## H2: Manage tokens written to access logs (HIGH, verified)

**Where:** the backend runs uvicorn with its default access log (`GET /api/registrations/<token> 200`), and nginx uses its default `combined` log (`GET /r/<token>`, plus the `Referer` header when someone navigates from the ticket page).

**Why HIGH:** the manage token *is* the participant's credential (view the ticket and **cancel**, D-012). CLAUDE.md and the README promise that tokens are never logged. In practice anyone with log access (operators, log shipping, support) can cancel someone's registration.

**Verified:** `docker compose logs backend` contains `GET /api/registrations/NOXPty0n…`, and `docker compose logs frontend` contains `GET /r/<token>`.

**Proposed tests:**
- `test_review.py::test_review_h2_manage_token_not_in_backend_logs`: a real uvicorn process with its log captured. GET and POST-cancel a registration by token, then assert the token doesn't appear in the log while the redacted path does.
- smoke probe: request `/r/<token>`, `/api/registrations/<token>` and a navigation with `Referer: …/r/<token>` through nginx, then assert the token isn't in `docker compose logs frontend`.

**Status: fixed.** Both tests were red first (token in the uvicorn log; smoke found `GET /r/smokeTOKEN…` in nginx's log). Both are green now. `Referrer-Policy: no-referrer` is served on every response.

**Fix:** a logging filter on `uvicorn.access` that redacts `/api/registrations/<token>` and `/r/<token>` (access logs stay useful). In nginx, a `log_format` that logs a redacted URI and no Referer, plus `Referrer-Policy: no-referrer` so tokens don't leak in `Referer` headers either.

## M1: CSRF on body-less organizer POSTs (MEDIUM, verified)

`POST /api/admin/events/{id}/cancel` with `Content-Type: application/x-www-form-urlencoded` and the organizer cookie returns **200** (verified). JSON endpoints are safe, because FastAPI refuses a `text/plain` JSON body with 422 (verified). `SameSite=Strict` stops *cross-site* attacks, but other origins on the **same site** (another port on `localhost`, a sibling subdomain in production) can submit a plain HTML form that cancels an event and emails everyone.

**Test:** `test_review_m1_mutating_admin_requests_require_json_or_custom_header`: a form-encoded POST to `/cancel` and `/logout` must give 415 or 403.
**Fix idea:** a middleware requiring `Content-Type: application/json` (or an `X-Requested-With` header) on every non-GET `/api/admin/*` and participant cancel, plus an `Origin` check.

## M2: Logout doesn't revoke the session (MEDIUM, verified)

The cookie is a stateless signed timestamp. A copy taken before logout still gets `GET /api/admin/me → 200` for up to 12h (verified), and open organizer SSE streams continue.
**Test:** `test_review_m2_cookie_invalid_after_logout`.
**Fix idea:** a server-side session row or a per-organizer "sessions valid after" timestamp checked on each request (and on each SSE tick).

## M3: Insecure production defaults are silent (MEDIUM)

`docker-compose.yml` falls back to the public dev `SESSION_SECRET` and `ORGANIZER_PASSWORD`, and `COOKIE_SECURE` defaults to false. Anyone who deploys the compose file with `APP_ENV=production` and no `.env` gets forgeable organizer cookies, and nothing warns them. The README says "dev-only", but nothing enforces it.
**Test:** `test_review_m3_production_refuses_dev_secrets`: `Settings(app_env="production", session_secret=<dev default>)` must fail to start, as must `cookie_secure=False`.

## M4: Local-time paths only tested in UTC (MEDIUM)

`format.ts` (`toLocalInput`/`fromLocalInput`) and every "your local time" label are tested only with `TZ=UTC` (vitest container) and Playwright `timezoneId: "UTC"`. The user base is UTC+6. A regression such as `getUTCHours()` instead of `getHours()` would pass every test.
**Test:** run `format.test.ts` under `TZ=Asia/Almaty` (round-trip `fromLocalInput(toLocalInput(iso)) === iso`, with the offset visible), plus one Playwright reschedule test with `timezoneId: "Asia/Almaty"`.

## M5: "Nothing else is needed on the host" is false (MEDIUM, verified by reading)

`scripts/smoke_compose.sh` uses `date -u -d '+7 days'`, which is GNU-only (BSD/macOS `date` fails), along with `curl`, `mktemp` and `bash`. `make test-smoke`, `make e2e` and `make proof` therefore don't work on a stock macOS host.
**Test:** run the smoke script with a `date` shim that rejects `-d`. **Fix idea:** compute timestamps inside a container, or say plainly in the README what the host needs.

## L1–L7 (LOW)

- **L1 UTC in emails:** dates are rendered `… 15:00 UTC`, while the UI uses the browser zone, so a participant in UTC+6 sees two different clock times for the same event. *Test:* the email contains an explicit zone (it does). This is a UX decision to record, or render in an event timezone (out of scope, §7).
- **L2 Stale non-reminder emails:** a ticket email queued for a registration that was cancelled before the worker sent it still goes out (with a code check-in will reject). The same applies to a promotion email after a quick cancel. *Test:* enqueue a ticket, cancel, dispatch, and assert the email is skipped. *Fix idea:* extend the send-time check to ticket and promotion emails.
- **L3 SSE cleanup only unit-tested:** `test_stream_releases_subscription_when_client_goes_away` covers the generator, not a real uvicorn disconnect. There is also no limit on concurrent streams per client. *Test:* expose a subscriber-count metric (dev only), open and close 200 streams against a live server, and assert the count returns to 0.
- **L4 Timing-sensitive tests:**
  - `test_keepalive_comments_on_idle_stream` (≥2 comments in 2.5s);
  - `test_sigkill_…` asserts a row is `sending` right after the kill (a kill between two batches would leave none);
  - `test_stats_never_inconsistent…` needs >5 snapshots.

  All are stable here (10–20 runs) but could flake on slow CI. *Fix idea:* poll with a deadline instead of fixed sleeps, and check for "at most one duplicate" rather than "something was in flight".
- **L5 Counter not DB-enforced:** overbooking is DB-enforced (CHECK). The counter matching the actual number of seat holders is only checked by tests (`assert_invariants`). *Fix idea:* a deferred constraint trigger, or drop the counter and count under the lock.
- **L6 Untested claim:** `docker compose up --build` without make (README "Quick start"). *Test:* a smoke variant using that command.
- **L7 Fan-out cost:** each open stream re-queries on each change. Fine at this scale. Would need a per-process snapshot cache keyed by `(event, version)` for large audiences.

---

## U1–U4: found after phase 7b by driving the real UI (not part of the phase 9 review)

Found on 2026-10-12 while testing the whole UI in Chrome against the running stack. None was fixed; they are disclosed here and in the README.

- **U1, live updates don't recover after a backend restart (MEDIUM, reproduced by hand).** With an event page open, restart the backend container: the page keeps showing the old numbers (it showed 2 seats left when 1 was left) until it is reloaded. `frontend/src/useEventStream.ts` handles `onerror` by setting `closed` when `readyState === EventSource.CLOSED`, but never creates a new `EventSource` after that. The browser's built-in retry only covers a dropped connection where it keeps the stream open; it doesn't cover the case where it gives up. The server side is fine: its Postgres listener does reconnect and resync (tested). **Test:** a component test with the fake `EventSource` that fails with `readyState = CLOSED` and expects a new instance after a backoff; optionally an E2E that restarts the backend. **Fix idea:** schedule a manual reconnect with capped exponential backoff until unmount.
- **U2, wrong note on a cancelled event (LOW).** The public page of a cancelled event still shows the "Cancel anytime…" text under the registration area. It is only text; no cancellation is possible.
- **U3, bad id in the URL (LOW).** `/events/not-a-uuid` shows the API's validation message instead of a "not found" page.
- **U4, no favicon (LOW).** The browser requests `/favicon.ico` and gets `index.html` (the SPA fallback), so the tab icon is the default one and the console may log an error.

---

## Requirements vs real tests (TEST_PLAN audit)

Every TEST_PLAN row resolves to existing tests (enforced by `make proof`: 43 PASS, 1 MANUAL). Weak spots, all documented:
- **B5 (last-seat race) through the UI:** two near-simultaneous clicks. Proven simultaneity is in the gated pytest tests only.
- **B6 (24h reminder):** no real 24h wait. Simulated clock plus an event 23h ahead on the real stack.
- **P7 (honest README):** manual. This review found two README/CLAUDE claims the code didn't support (H2 "tokens never logged", M5 "only Docker + make").
