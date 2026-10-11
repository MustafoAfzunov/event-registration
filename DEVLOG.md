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
