# Dev Log

Append-only. One entry per phase (or significant session), with a timestamp from `date -Iseconds`.

---

## 2026-10-11T09:51:04+06:00 · Phase 0: Architecture and plan

**Done**
- Wrote `docs/ARCHITECTURE.md`: assumptions A1–A10, component diagram, technology choices with justification, mechanisms for every tricky behaviour (last-seat lock, FIFO promotion, outbox, reminders, reschedule, check-in, SSE fan-out), state machine, data model with constraints, edge-case decisions E1–E27, out-of-scope list.
- Wrote `docs/API.md` (endpoints, payloads, stable error codes), `docs/PLAN.md` (phases 1–10 with files, named tests and DoD), `docs/TEST_PLAN.md` (every requirement mapped to ≥1 named test).
- Wrote `CLAUDE.md` (project rules) and `DECISIONS.md` (D-001 … D-020).

**Tests:** none exist yet. No application code was written in this phase. A consistency check confirmed that every test named in TEST_PLAN appears in PLAN.

**Not done / open questions for the user**
- Assumptions that need a yes/no from the user: A1 (single shared organizer password), A4/D-016 (reminders only to confirmed), A6/D-009 (one reminder per schedule version), A9/D-012 (ticket only via email, never in the API response).

**Surprises:** none yet.

**Next:** phase 1 (scaffold + infra). Not started.

---

## 2026-10-11T10:17:59+06:00 · Phase 1: Scaffold and infra

**Done**
- **Compose stack** (`name: eventreg`): `db` (postgres:16), `mailpit` (v1.31), `migrate` (one-shot `alembic upgrade head`), `backend` (FastAPI, 2 uvicorn workers), `frontend` (nginx: React build + `/api` proxy). Every long-running service has a healthcheck. `make up` returns once all are healthy.
- **Backend:** `create_app()` factory, settings, injectable `Clock`, async engine. `GET /api/health` + `/health` run `SELECT 1` with a 2s budget and return 200 or 503.
- **Schema:** hand-written migration `0001` with all three tables, 4 enums, the queue sequence, named CHECKs, the partial unique index `uq_registrations_active_email`, and partial indexes. ORM models mirror it exactly.
- **Tests:** real-Postgres pytest fixtures (safety check refuses non-`_test` DBs), vitest + Testing Library, and `scripts/smoke_compose.sh` (isolated project, real `make up`, 7 probes, full teardown).
- **Tooling:** Makefile targets `up down clean logs ps migrate test test-backend test-frontend test-smoke test-all lint`. Everything runs in containers.
- README quick start. CLAUDE.md commands updated. PLAN, TEST_PLAN and API docs updated to match. D-021 … D-030.

**Tests**: `make lint && make test-all` → ruff/format/mypy --strict clean, eslint/tsc clean. **Backend 20 passed**, **frontend 4 passed**, **smoke 7/7** (stack healthy in ~15s). Also ran `SMOKE_NO_CACHE=1` once (images rebuilt with no build cache): 7/7.

**Verification beyond the suite**
- Mutation checks: a model-only column makes `test_models_match_migrations` fail. Removing the partial unique index from the migration makes both the drift test and `test_active_email_unique_index_rejects_second_active_row` fail. Both were reverted.
- Manual in the browser at :8080: "Backend: ok · Database: ok". With `docker compose stop db`, both curl and the UI show 503 / "database is unavailable". After `start db` it recovers to 200 without a backend restart (`pool_pre_ping`).

**Surprises**
- The first smoke run caught a **real bug that unit tests missed**: the `alembic` CLI in the `migrate` container couldn't import `app` (pytest had added the path). Fixed with `prepend_sys_path = .` + `path_separator = os` in `alembic.ini`.
- Host npm 10.8 crashed (`Cannot read properties of null (reading 'edgesOut')`). The lockfile was generated in `node:22-alpine` instead (D-026).
- typescript-eslint doesn't support TS 7 yet, so TS is pinned at 6.0.3 (D-025).

**Not done / known gaps**
- No domain features (phase 2+). No worker service (moved to phase 3, D-023).
- Python transitive deps aren't locked (D-024).
- The test-DB init script only runs on a fresh volume. Volumes created before this phase need `make clean`.
- `/health` (without the `/api` prefix) isn't reachable through nginx on :8080, only on backend :8000. This is intentional (D-021).

**Next:** phase 2 (registration core + waitlist + locking). Not started.

---

## 2026-10-11T14:50:17+06:00 · Phase 2: Registration core, waitlist and locking

**Context:** the user approved the phase 2 plan as part of the phase 3 request (D-031). Phase 2 is committed on its own, before phase 3.

**Done**
- **API:**
  - Organizer: login/logout/me (signed httpOnly SameSite=Strict cookie), events create/list/patch. No delete, by design.
  - Public: events list/get, register.
  - Participant: `GET /api/registrations/{token}`, `POST …/cancel`.
  - One error envelope for all errors (`DomainError`, validation, 404/405).
- **Concurrency core** (`app/services/seats.py`): `lock_event` (`SELECT … FOR UPDATE`) starts every seat-changing transaction, with lock order event → registrations. `seats_taken` is changed only under the lock. FIFO promotion runs in the same transaction that frees the seat (cancel, capacity increase).
- **Registration:**
  - Email trimmed, validated (ASCII, no DNS) and lowercased.
  - A duplicate returns the existing row (200, no email).
  - Waitlist via `queue_seq` taken under the lock.
  - Ticket-code collisions retried in a SAVEPOINT.
  - The unique-index backstop is handled.
- Outbox rows (ticket / waitlisted / promoted / cancelled) are written in the same transaction, with dedupe keys. **Not sent yet.**
- **Test tooling:** `tests/concurrency.py` (lock gate proven via pg_locks), `tests/invariants.py` (checked after every concurrency test), helpers, `make test-concurrency-loop N=20`.
- **Smoke:** a new 8th probe runs organizer login → create event → register ×2 (confirmed, waitlisted) through nginx on the real 2-worker stack.

**Tests:** `make lint && make test-all` → lint/types clean, **backend 98 passed**, frontend 4 passed, smoke 8/8.

**Concurrency evidence**
- `make test-concurrency-loop N=20`: **20/20 runs passed** (6 tests each, ~4s per run). Since the last-seat test does 25 gated rounds, that's **500 proven last-seat races**.
- Your 6 scenarios:
  1. 20 parallel / 5 seats → 5 + 15, positions 1..15.
  2. Last seat, gated.
  3. Same email ×10, identical and case/whitespace variants → 1 row, 1 outbox row.
  4. Case/whitespace variants.
  5. FIFO promotion, including skipping a waitlister who left.
  6. 5 cancels + 10 registrations in parallel, random order: an observer saw confirmed ≤ 5 throughout, the 5 oldest waitlisters got the seats, and no newcomer jumped the queue.
- **Mutation** (`FOR UPDATE` removed): 3/6 concurrency tests failed, every time with `CheckViolation ck_events_seats_taken_range`. The DB refused to overbook (D-040). Restored.

**Surprises**
- The first gated run reported "1/20 waiting" while all 20 were blocked. `pg_stat_activity` is snapshotted per transaction, so the poller now runs in AUTOCOMMIT (D-033).
- The deployed-stack smoke probe got 422 for `@smoke.test`. email-validator rejects special-use domains, which is correct, so it's now pinned in tests (D-042).
- SQLAlchemy 2.1 types `Select` variadically (`Select[Event]`). mypy caught it.

**Not done / known gaps**
- Emails aren't sent (phase 3). No check-in, live updates, reminders, reschedule or event cancel endpoints (phases 4–6). No UI (phase 7).
- E5/E8 edge cases (cancelled event, checked-in ticket) are tested by setting state via SQL until those endpoints exist.
- Concurrency tests are in-process (one Python process, many Postgres connections). The multi-process HTTP stress test is phase 8.
- No rate limiting. Duplicate registration reveals registration status (D-036).

**Next:** phase 3 (email worker), in this same session, per the user's instruction.

---

## 2026-10-11T15:19:41+06:00 · Phase 3: Email outbox worker and tickets

**Done**
- **Worker** (`python -m app.worker`, compose service `worker` with heartbeat healthcheck): `Dispatcher` behaviour:
  - Claims batches with `FOR UPDATE SKIP LOCKED` and a lease.
  - Fencing via `attempts`.
  - SMTP to Mailpit via aiosmtplib.
  - Exponential backoff, `failed` after 8 attempts.
  - SIGTERM finishes the in-flight message and releases the rest.
  - Startup check that lease > worst-case batch time.
- **Emails:** ticket (code + manage link), waitlist notice (position, no code), promotion (with ticket), cancellation confirmation. Rendered at enqueue time. Deterministic Message-ID from the dedupe key.
- **Delivery guarantee:** exactly-once *enqueue* (phase 2: same transaction + unique key), **at-least-once delivery** (user decision, D-043), documented in README and ARCHITECTURE §4.5.
- **Test infrastructure:** separate `mailpit-test` service, a Mailpit API client, fault-injecting senders (real dead-port failures, simulated crashes), and real worker subprocess tests.
- Smoke now has 9 probes, including "worker delivered exactly 2 emails" on the real stack.

**Tests:** `make lint && make test-all` → clean. **Backend 116 passed**, frontend 4 passed, smoke 9/9.
- Your 5 required tests, all verified in Mailpit:
  - `test_one_email_per_registration`
  - `test_repeat_registration_sends_no_second_email`
  - `test_promotion_sends_exactly_one_email_with_ticket`
  - `test_worker_restart_mid_batch_does_not_duplicate`
  - `test_smtp_failure_retries_then_sends_once`
- **Real-process restarts:**
  - SIGTERM mid-batch, then restart: exactly 20/20, no duplicates.
  - SIGKILL mid-batch, then restart: all 20 delivered, ≤1 duplicate (the at-least-once window).
- **Flakiness:** the 17 email/worker tests passed **10/10 consecutive runs**.

**Mutation checks (do the tests have teeth?)**
- Fence removed: initially **not caught**. The test reported after the new owner had finished, so the status check alone protected the row. Rewritten to report while the new owner is still sending, and now caught (D-044).
- `FOR UPDATE SKIP LOCKED` removed: initially **not caught**, because two ungated dispatchers never overlapped. Added `test_concurrent_claims_are_disjoint` with a table-lock gate (10 claimers proven blocked), and now caught: "a row was claimed by two dispatchers" (D-047).

**Manual demo on the dev stack (phase 3 DoD):** stopped `mailpit` and registered `outage@example.com`. The API returned 201 and the outbox row went `pending`, attempts 2, `SMTPConnectError`, retry scheduled. After `docker compose start mailpit` the email arrived about 5s later, **1 copy**, row `sent` on attempt 3.

**Surprises**
- Both mutants above survived the first version of the tests. That was the most valuable finding of this phase.
- The API said "Your ticket was sent" while the email was only queued, which the outage demo made false. Now it says "on its way" (D-053).

**Not done / known gaps**
- The manage link in emails points at `/r/{token}`, a UI page that arrives in phase 7. The API behind it works.
- No reminder scheduler yet (phase 6). No HTML emails. No SMTP TLS/auth (Mailpit only).
- Exactly-once *delivery* isn't achievable over SMTP. The one duplicate window is documented and tested.
- `attempts` also counts releases on graceful shutdown (D-045).

**Next:** phase 4 (check-in + organizer stats). Not started.

---

## 2026-10-11T20:00:13+06:00 · Phase 4: Check-in and organizer stats

**Done**
- `POST /api/admin/events/{id}/checkin`: one atomic conditional UPDATE (`status='confirmed'` → `checked_in`). Input normalization (case, spaces, dashes, O→0, I/L→1). Distinct errors: `invalid_code_format` 422, `ticket_not_found` 404, `already_checked_in` 409 (with the original time), `ticket_cancelled` 409, `ticket_waitlisted` 409, `event_cancelled` 409. No event lock (D-054).
- `GET /api/admin/events/{id}/stats`: confirmed (not arrived), checked_in, registered, waitlisted, cancelled, seats_left, email delivery counts. All from **one SQL statement** = one consistent snapshot (D-056).
- `GET /api/admin/events/{id}/registrations[?status=]`: list with formatted codes and waitlist positions.
- Organizer auth: the existing signed-cookie login (A1/D-011) now covers check-in, stats and the list (D-058).
- `tests/concurrency.py::row_lock_gate`. Smoke probe #10: reads the ticket code from the real email in Mailpit, checks in via nginx, a second scan gets 409, stats show checked_in=1.

**Tests:** `make lint && make test-all` → clean. **Backend 146 passed**, frontend 4, smoke 10/10.
- Double check-in, sequential: 200 then 409 `already_checked_in` with the original timestamp.
- Double check-in, parallel: 10 scanners, gated (all proven blocked on the row) × 10 rounds → exactly 1 × 200 + 9 × 409, every round.
- Wrong code: 404. Malformed: 422. Cancelled and waitlisted tickets: distinct 409 codes. Other event's code: 404.
- Check-in vs cancel race, gated, both queue orders asserted explicitly (D-059).
- Stats after every kind of transition: a 17-step scenario (register, waitlist, duplicate, cancel waitlisted, cancel confirmed + promotion, check-in, failed check-ins, cancel with empty waitlist, re-register, capacity up with promotions, rejected capacity down, promoted person cancels, capacity down to taken, all arrive). Each step is checked against hand-computed numbers **and** an independent SQL recount **and** the invariants.
- Stats under 40 parallel writes: every sampled snapshot satisfied the invariants.
- **Flakiness:** the concurrency subset (check-in races + concurrent stats) passed **20/20 runs**.
- **Mutation:** removing `status='confirmed'` from the check-in UPDATE fails 6 tests.

**Surprises**
- Bug found by a test: timestamps in error `details` used `+00:00` while bodies used `Z`. Unified via `app/timefmt.iso_utc` (D-057).
- The first version of the check-in vs cancel test accepted either winner, which proves little. It's now deterministic per queue order.
- Changed the API contract: `ticket_not_active` split into `ticket_cancelled`/`ticket_waitlisted` (D-055), per your "clear error codes" request.

**Not done / known gaps**
- The stats counter doesn't update live yet (phase 5 SSE). No check-in UI yet (phase 7).
- No separate door-staff role. Check-in uses the organizer password (D-058).
- No rate limiting on check-in attempts. The code isn't a credential (D-051), and the endpoint is organizer-only.

**Next:** phase 5 (live updates via SSE). Not started.

---

## 2026-10-12T02:16:50+06:00 · Phase 5: Live updates (SSE)

**Done**
- `app/live/broker.py`: one LISTEN connection per backend process. It wakes only the subscribers of the changed event, reconnects after 1s, and resyncs everyone after a reconnect. `notify_event_changed` is called inside the transaction of register, cancel (incl. promotion), capacity/title update, check-in, and email completions.
- `app/live/sse.py` + `app/api/stream.py`:
  - `GET /api/events/{id}/stream` (public `availability`: seats left, waitlist, status).
  - `GET /api/admin/events/{id}/stream` (organizer `stats`).
  - Behaviour: `retry: 3000`, snapshot on connect, gap-closing wake, changed-only frames, keepalive comments, 401/404 as JSON before streaming, `session_expired` frame at login expiry.
- Uvicorn `--timeout-graceful-shutdown 5`. Pure-ASGI `X-Backend-Pid` header outside production.
- Test infrastructure: real uvicorn processes (`a`, `b` single-worker; `multi` with `--workers 2`), an SSE client over real HTTP. Smoke probe #11: 6 streams through nginx to the 2-worker compose backend.

**Tests:** `make lint && make test-all` → clean. **Backend 160 passed** (14 new live tests), frontend 4, smoke 11/11.
- Two clients (organizer and public streams, on two different backend processes, with writes from a third process) all receive registration, waitlist, cancellation+promotion and check-in. The public streams correctly stay silent on check-in.
- `--workers 2`: streams proven on both worker pids (via the header). A write handled by one worker reached streams on the other.
- No leaking: wire level (5 writes to another event give 0 frames) and broker level (other event's subscriber not woken).
- Reconnect, including to a *different* process: the first frame is the current snapshot.
- Listener killed via `pg_terminate_backend` + immediate write: the change still arrives (resync).
- Rollback: no NOTIFY delivered. Commit: delivered.
- **Flakiness:** `test_live.py` passed **10/10 runs** (real processes).
- **Mutation:**
  - No notify on registration: 3 tests fail.
  - Broker ignores event id: the routing test fails. The wire-level leak test can't see it, as predicted, because unchanged snapshots aren't re-sent. That's why the broker test exists.
  - No resync after reconnect: the outage test fails 3/3.
- **Real stack:** 6 SSE streams via nginx, served by 2 distinct workers, all received the update.

**Surprises**
- httpx's ASGI transport can't test streams (it buffers whole responses), which forced real-server tests. That's a better proof anyway.
- `BaseHTTPMiddleware` was avoided for the pid header because of known streaming/disconnect issues. Pure ASGI instead.

**Not done / known gaps**
- No frontend consumer yet (`EventSource` hook + screens are phase 7).
- The pending→sending email transition isn't pushed live (D-063).
- One snapshot query per change per open stream. Fine for this scale. Not load-tested beyond the smoke test (phase 8).
- No `Last-Event-ID` replay, by design (D-066).
- The phase 2 concurrency loop wasn't re-run 20× this phase. The full suite (which includes those tests once) passed after adding `pg_notify` to the locked transactions.

**Next:** phase 6 (scheduler: reminders, reschedule, event cancel). Not started.

---

## 2026-10-12T03:08:26+06:00 · Phase 6: Scheduler (reminders), reschedule, event cancel

**Done**
- `app/scheduler.py`: DB-driven ticks. Each picks the next due event lacking reminders for its current `schedule_version` with `FOR UPDATE OF e SKIP LOCKED`, upserts one reminder per confirmed person (key `reminder:{event}:v{version}:{email}`, re-arming only `skipped` rows), notifies, and commits. No in-memory timers. Runs in the worker next to the dispatcher. Compose healthcheck checks both heartbeats. `SCHEDULER_TICK_SECONDS` is configurable.
- Dispatcher send-time check for reminders: event scheduled, same version, not started, person still confirmed. Otherwise `skipped` with a reason. Content is re-rendered with the current ticket and date (D-068).
- `POST /api/admin/events/{id}/reschedule`: `starts_in_past` 422, same time = no-op. Otherwise version +1, pending old-version reminders skipped, "New date" email to confirmed + waitlisted + checked-in (D-069), live update.
- `POST /api/admin/events/{id}/cancel`: idempotent. "Cancelled" email to the same group, pending reminders skipped, every later mutation 409.
- Policies, as decided in ARCHITECTURE A6/E16–E18:
  - Window `[start−24h, start)`.
  - Already inside the window (created, promoted, registered or rescheduled late) means the reminder goes out at the next tick.
  - Downtime means a late reminder if the event hasn't started, never after the start.

**Tests:** `make lint && make test-all` → clean. **Backend 191 passed** (31 new), frontend 4, smoke 12/12. Your list:
- **3 scheduler instances:** 5 rounds of 3 concurrent ticks + 3 concurrent dispatchers gave 5 people 5 reminders. A gated variant (3 instances proven blocked at once) over 30 events: each event's reminders were enqueued by exactly one instance. **3 real worker processes**: 8 confirmed got exactly 8 reminders, the 2 waitlisted got none.
- Not sent to cancelled or waitlisted people. Cancelled after enqueue means skipped at send time.
- Promoted participant: exactly one reminder (and the new ticket code in it).
- **Restart between claim and send:** a dispatcher crash after 1/3 sends, an early restart that sends nothing (lease held), a tick that doesn't re-enqueue, then after the lease all 3 delivered exactly once. A scheduler crash before commit rolls back, and the next tick does it.
- **Reschedule:** v1 reminders sent, then reschedule, then nothing until the new window, then exactly one v2 reminder with the new date. Pending v1 voided. A v1 reminder **claimed before** the reschedule is skipped at send.
- **Past / near future:** past or now → 422 with nothing changed. Moved to 2h ahead → one reminder with the new date on the next tick.
- **Also:** window opens exactly at 24h, late reminder after downtime, none after the start, events created <24h ahead, cancel+re-register gets one reminder, the skipped→re-armed path, check-in before the reminder means skipped, event cancel blocks everything, and live streams get reschedule/cancel.
- **Flakiness:** the phase 6 tests plus worker-process tests passed **10/10 runs**.
- **Mutation:**
  - Version check removed: the claimed-before-reschedule test fails.
  - Voiding pending reminders removed: the voiding test fails. Notably *no stale email* was sent even then, because the send-time check caught it (two independent layers).
  - Re-arm removed: the re-arm test fails.
- **Smoke on the real stack** (tick 2s): exactly 1 reminder. Reschedule → 1 "New date" email + 1 reminder for the new date.

**Surprises (and fixes)**
- `sqlalchemy.text()` parsed `':v'` inside a SQL string literal, and even inside a SQL **comment**, as a bind parameter. The query is rewritten as `':' || 'v'`.
- The SKIP LOCKED partition test failed at first. Under READ COMMITTED an instance can revisit an event that another just finished, so SKIP LOCKED isn't the exactly-once mechanism; the dedupe key is. The code and test now report only real enqueues (D-067).
- `rowcount` is -1 through the ORM session for `INSERT … ON CONFLICT` (verified). The scheduler now uses `RETURNING`, and so does phase 2's `enqueue()`, whose boolean was silently always true (D-070). Pinned by a test.

**Not done / known gaps**
- An accepted tiny race: a reminder already passing through SMTP when a reschedule commits carries the old date, and the "New date" email follows (D-072).
- Reminder lateness is up to one tick (30s) plus dispatch latency.
- No UI for reschedule or cancel yet (phase 7).
- The phase 2 20× concurrency loop wasn't re-run. The full suite passed.
- The dev stack on :8080 still runs the images from 12h ago. Run `make up` to get phase 6 there.

**Next:** phase 7 (frontend). Not started.

---

## 2026-10-12T03:27:37+06:00 · Phase 7: Frontend

**Done** (React 19 + Vite + React Router 8, no state library)
- **Public:** events list, event page (details, **live seats left** via SSE, register form with outcomes *confirmed* / *waitlisted #N* / *already registered (no second seat)*, every error code in plain language, form hidden when cancelled or started), ticket page `/r/:token` (big ticket code, waitlist position, checked-in and cancelled states, cancel with confirm).
- **Organizer:** login and guard (redirects back to the requested page), events list + create, dashboard (live counters incl. "not arrived yet", participant list with status tabs refreshed on every live frame, edit title/description/seat limit, reschedule with "N notified", cancel event, login-expired prompt), check-in screen (autofocus, Enter, big green/red result per error code, cleared on success / selected on error, live "N / M arrived").
- Loading and error states on every page. `useEventStream` hook. `api.ts` + `errors.ts` error map. Minimal CSS.
- Smoke: deep links (`/events/x`, `/r/x`, `/admin/…`) are served by the nginx SPA fallback.

**Tests:** `make lint && make test-all` → clean (tsc, eslint incl. react-hooks). **Frontend 38 passed** (was 4), backend 191, smoke 12/12. No `act()` warnings.

**Manual check on the real stack** (built-in browser, two tabs, real backend / SSE / Mailpit):
1. `/admin` redirected to login. Logged in, created the event "Browser demo" (1 seat), and the dashboard showed the live badge.
2. In tab 2 (public page), registered `first@` ("You're in!"). The page flipped live to "Full", button "Join waitlist". Registered `second@` ("#1 on the waitlist"). Tab 1's counters and participant list updated **without reload**.
3. Opened `first@`'s manage link from the real email in Mailpit, and the ticket page showed the code. Cancelled: tab 1 showed `first@` cancelled and `second@` **promoted**, live. *(The cancel was sent with curl to the same API, because the native `confirm()` dialog stalls the automated browser pane. The button flow is covered by component tests, both confirm and decline.)*
4. Check-in in tab 2: typed `c3yv k2c1` (lowercase, space) and got a green "Welcome!". The same code again was red "Already used" with the time, and the code stayed selected. Tab 1 moved to 1 arrived live.
- Environment note: the browser pane once blocked the JS bundle in a fresh tab (`ERR_BLOCKED_BY_CLIENT`, client-side). It loaded fine on retry. Not an app issue.

**Bugs found by tests in this phase**
- The reschedule form was keyed by `starts_at`. A successful reschedule remounted it and wiped the "N participants notified" message. It's now keyed by event id.
- The first `useEventStream` version called `setState` synchronously in an effect (react-hooks lint). It was reworked to URL-keyed state, which also prevents showing a previous event's numbers after navigation.

**Not done / known gaps**
- No automated browser E2E yet (phase 8). The component tests mock the API.
- The UI is in English only, with minimal styling, and has no explicit accessibility audit (labels and roles are used throughout, because tests query by them).
- Times are shown in the browser's timezone. There's no per-event timezone.
- The organizer participant list isn't paginated (fine for event-sized lists).

**Next:** phase 8 (E2E and proof). Not started.

---

## 2026-10-12T03:53:20+06:00 · Phase 8: E2E and proof

**Done**
- **Playwright E2E** (`e2e/`, official image v1.64.0, Chromium, 0 retries), run by `scripts/e2e.sh` / `make e2e` against an isolated stack (tick 2s) with real Mailpit:
  - **Two contexts:** registering in tab A updates tab B's seat counter **without reload** (asserted with a window marker).
  - Last-seat race through the UI (3 rounds): exactly one "You're in!", one "full".
  - **Cancel promotes:** the holder cancels from the real ticket-email link (real confirm dialog). The waitlisted person gets exactly one "A seat opened up" email, and its link shows the ticket.
  - **Check-in once:** door tab green, then red "Already used". The organizer dashboard tab goes 0 → 1 live, without reload.
  - **Reschedule** via the dashboard UI: "2 participants notified". Mailpit has exactly one "New date" email for the confirmed and the waitlisted person. The public tab shows the new date live.
  - Plus: ticket email → ticket page, duplicate registration (no second seat, one email), reminder (exactly one, none for waitlisted).
- **`scripts/stress.py`** / `make stress`: storm + mixed phase, 17 invariants (D-081).
- **`make proof`**: all layers, then the requirement table from JUnit (D-082). The plan is machine-checked.

**Full suite = `make proof` (final run):**
- Steps: lint PASS (14s), backend PASS (191 tests, 80s), frontend PASS (38 tests), concurrency loop ×5 PASS, smoke PASS (12 probes), e2e PASS (9 tests, 34.6s), stress PASS (17/17).
- **238/238 test cases passed. Requirements: 43 PASS, 1 MANUAL (P7). PROOF PASS.**
- Stress numbers: 250 requests in 2.22s, 112.7 req/s, p50 1421ms, p95 2104ms, both backend workers seen. Mixed phase: 20/20 freed seats went to the oldest waitlisters, 0 newcomers jumped the queue.
- E2E passed 3 consecutive times on fresh stacks (first run, the JUnit run, the proof run), excluding the deliberate mutant run.

**Evidence the new checks have teeth**
- A frontend mutation (event page ignores live data) failed 2 E2E tests while every backend test passed (D-084).
- The proof report was fed a fake plan with bogus test names, which showed as MISSING and gave PROOF FAIL.
- The first report run flagged real drift in TEST_PLAN, now fixed:
  - P3 and P6 had no resolvable references;
  - E1 was "see B2";
  - there was a duplicate E1 row;
  - a stress script name was planned in phase 0 but never created.

**Surprises**
- The browser pane / Playwright had no flakiness. The UI last-seat race is not provably simultaneous (two clicks), which is documented (D-080). The proven race is in pytest.
- Single-event throughput is bounded by the row lock (about 115 req/s). That's an honest trade-off, now in the README.

**Not done / known gaps**
- E2E covers Chromium only (no Firefox/WebKit). No mobile viewport.
- The E2E last-seat race isn't gated. No load test across many events at once. No soak test (long-running SSE, memory).
- `make proof` takes about 10 minutes and needs network for the first image pulls.
- P7 (honest README) stays manual, by nature.

**Next:** phase 9 (independent review and hardening). Not started.
