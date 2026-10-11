# Decisions Log

Append-only. Timestamps come from `date -Iseconds`. Superseded entries stay, and new entries reference them.
Format: **D-NNN, title** · When · Decision · Why · Rejected alternatives.

---

### D-001: Async FastAPI + SQLAlchemy 2.0 async + psycopg 3
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** async throughout. One DB driver (psycopg 3) for app, Alembic and LISTEN/NOTIFY.
- **Why:** SSE keeps one long-lived connection per browser tab, which is cheap on asyncio. A single driver means one set of behaviours to understand.
- **Rejected:** sync SQLAlchemy in a threadpool (a thread per SSE client); asyncpg (would need psycopg anyway for sync Alembic, so two drivers).

### D-002: Alembic migrations, hand-written constraints
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** Alembic with manual review. Partial unique indexes and CHECKs are written explicitly.
- **Why:** autogenerate misses or mangles partial indexes, and these constraints carry the correctness guarantees.
- **Rejected:** `create_all()` at startup (no versioning).

### D-003: Concurrency via per-event `SELECT … FOR UPDATE` under READ COMMITTED
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** every seat-changing operation locks the event row first. Lock order is event, then registrations.
- **Why:** simple to reason about, deterministic, needs no retry loops, and serializes only per event.
- **Rejected:** SERIALIZABLE (correct, but every call site needs retry-on-40001); optimistic version column (retries again); advisory locks (invisible in the schema, easy to forget).

### D-004: Denormalized `events.seats_taken` with CHECK (≤ capacity)
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** keep the counter in the same transaction as status changes, guarded by `CHECK (seats_taken BETWEEN 0 AND capacity)`.
- **Why:** this makes overbooking impossible at DB level even if application logic regresses. An invariant test checks counter == actual count.
- **Rejected:** count-only (no DB-level overbooking guard); trigger-maintained counter (logic hidden from readers).

### D-005: Partial unique index for "one active registration per email per event"
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** `UNIQUE (event_id, email_normalized) WHERE status <> 'cancelled'`.
- **Why:** this enforces the duplicate rule in the DB while still allowing re-registration after a cancel (a new row, so history is kept).
- **Rejected:** a full unique index + reusing the cancelled row (loses history, and ticket-code reuse is confusing).

### D-006: FIFO by a global sequence `queue_seq`, assigned under the event lock
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** waitlist order = `queue_seq` ASC.
- **Why:** the sequence is unique and monotonic, and because it's assigned under the lock, sequence order equals arrival order. Timestamps have resolution and transaction-start issues.
- **Rejected:** `created_at` ordering; a stored position column (needs renumbering on every cancel).

### D-007: Transactional outbox + DB-polling worker (no broker)
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** `email_outbox` rows are inserted in the business transaction with a unique `dedupe_key`. The worker claims rows with `FOR UPDATE SKIP LOCKED` and a lease, sends via aiosmtplib, retries with exponential backoff, and marks `failed` after 8 attempts.
- **Why:** state change and email intent are atomic. It survives Mailpit or worker outages and is safe with N workers.
- **Rejected:** sending SMTP in the request (lost or phantom emails); FastAPI BackgroundTasks (lost on crash); Celery + Redis (extra infra for no gain at this scale).
- **Honest limit:** enqueue is exactly once; SMTP delivery is at least once (a crash between SMTP accept and DB commit can duplicate). Mitigated with a deterministic Message-ID. Will be stated in the README.

### D-008: Reminder scheduler = idempotent periodic scan, outbox key is the record
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** every 30s, `INSERT … SELECT … ON CONFLICT (dedupe_key) DO NOTHING` for confirmed registrations where `starts_at - 24h <= now < starts_at`. The key is `reminder:{event}:v{schedule_version}:{email_normalized}`.
- **Why:** stateless, restart-safe, multi-replica-safe, and it catches up after downtime. Keying on email means cancel + re-register doesn't produce a second reminder.
- **Rejected:** APScheduler/cron jobs per event (in-memory state, jobs lost on restart, must be rescheduled on reschedule); a `reminder_sent` boolean on registrations (breaks with reschedule and re-registration).
- **Decided:** no reminder once the event has started (a reminder after the start is noise).

### D-009: Reschedule bumps `schedule_version`; stale reminders skipped at send time
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** reschedule = new `starts_at` + `schedule_version += 1` + `rescheduled` email to confirmed and waitlisted. The worker skips a reminder whose version or registration status is stale.
- **Why:** the latest reminder always matches the real date, with no need to hunt down and delete queued rows.
- **Interpretation:** "exactly one reminder" = one per person per schedule version. A reschedule after a reminder was sent legitimately triggers one new reminder for the new date.

### D-010: Live updates via SSE + Postgres LISTEN/NOTIFY; snapshot protocol
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** `pg_notify` inside write transactions (delivered on commit). One listener connection per API process fans out to per-event asyncio queues. SSE sends full count snapshots (on connect and on change) and a keepalive every 15s. Uvicorn runs with 2 workers by default to keep fan-out exercised.
- **Why:** one-directional data, native browser reconnect, no extra infra. A snapshot protocol tolerates lost or duplicate notifications.
- **Rejected:** WebSocket (bidirectional, unneeded); Redis pub/sub (extra service); client polling (not "live", and more load).

### D-011: Organizer auth = shared password → signed httpOnly SameSite=Strict cookie
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** `ORGANIZER_PASSWORD` from env, constant-time compare, itsdangerous-signed cookie with a 12h TTL. Check-in staff use the same login.
- **Why:** the brief has a single organizer role. Cookies work with EventSource and a same-origin nginx proxy, and SameSite=Strict + JSON-only bodies handles CSRF for this scope.
- **Rejected:** JWT in localStorage (XSS-exposed, and EventSource can't send headers); token in a query string (leaks into logs); a full user/role system (out of scope).

### D-012: Participants authenticate by emailed capability link; ticket only via email
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** `manage_token` (32 random bytes) in the email link grants view and cancel. The registration API response never contains the ticket code or token.
- **Why:** otherwise anyone typing someone else's email (the duplicate path) would get that person's ticket and cancel rights.
- **Trade-off:** `manage_token` is stored in plaintext because the outbox body already contains the link. Documented, not hidden.

### D-013: Ticket code = 8-char Crockford base32
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** about 40 bits of entropy, displayed `XXXX-XXXX`. Input is normalized (case, spaces, dashes, O→0, I/L→1). Unique index plus retry on collision.
- **Why:** typeable at the door (the brief: typing replaces a scanner), with no ambiguous characters.

### D-014: Email normalization = trim + lowercase whole address
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** lowercase the full address, validate syntax with email-validator (no DNS), keep the original for display.
- **Why:** this matches user expectation and practice. Gmail dot and `+tag` folding is provider-specific and would wrongly merge distinct addresses at other providers.

### D-015: Edge-case policies
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** (full table in ARCHITECTURE §6)
  - Capacity cannot be reduced below `seats_taken` (409). We never bump confirmed people.
  - Capacity increase promotes FIFO immediately.
  - Cancel after check-in returns 409. Cancel after event start returns 409. Cancel is idempotent.
  - Registration closes at `starts_at`.
  - Re-registering after a cancel creates a new row at the back of the queue.
  - A duplicate registration returns the existing one (200) and sends no new email.
  - Event cancel notifies confirmed + waitlisted and blocks every mutation.
  - A failing promotion email never undoes the seat.
- **Why:** deterministic, explainable rules that never take a seat away from someone silently.

### D-016: Reminder recipients = confirmed only; reschedule/cancel-event recipients = confirmed + waitlisted
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** as stated.
- **Why:** waitlisted people have no seat, so a reminder would mislead them. A date change or cancellation does affect their decision to keep waiting.
- **Assumption:** flagged to the user and can be revisited.

### D-017: Single origin via nginx reverse proxy
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** the frontend container (nginx) serves the build and proxies `/api` to `backend:8000` over the compose network. The backend is also exposed on :8000.
- **Why:** separate services still talk over the network, while the browser sees one origin: no CORS and simple cookies. `proxy_buffering off` for SSE.

### D-018: Injectable Clock; no SQL `now()` in business logic
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** services receive `now` from a `Clock` and bind it as a parameter.
- **Why:** reminders, past-event checks and reschedules become testable without waiting 24h or patching time globally.

### D-019: Tests run against real Postgres and real Mailpit
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** a dedicated `eventreg_test` database in the compose Postgres, tables truncated per test. Concurrency tests use separate connections. Email integration tests read the Mailpit HTTP API. E2E uses Playwright against the full stack.
- **Why:** locking and constraint semantics can't be faked. The brief asks for proof.
- **Rejected:** SQLite (different locking); mocking the DB.

### D-020: Event has no end time; check-in is allowed any time while scheduled
- **When:** 2026-10-11T09:51:04+06:00
- **Decision:** no check-in time window.
- **Why:** the brief defines no end time, and inventing one adds rules nobody asked for. Recorded as an assumption.

---
<!-- Phase 1 -->

### D-021: Health served at both `/api/health` and `/health`
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** one handler, two routes. `/api/health` is the contract (docs/API.md) and is reachable through nginx. `/health` is the alias the user asked for, used by the container healthcheck.
- **Why:** this keeps the documented `/api` prefix while honouring the request. The DB probe has a 2s budget (`asyncio.timeout`), so a hung DB yields a 503, never a hung healthcheck.

### D-022: Migrations run in a one-shot `migrate` compose service
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** `migrate` (backend image, `alembic upgrade head`) must exit 0 before `backend` starts (`service_completed_successfully`).
- **Why:** the backend runs 2 uvicorn workers. Migrating in each worker's startup would race, and Alembic takes no lock.
- **Rejected:** migrating in the backend entrypoint (breaks once there are several replicas); migrating at app startup.

### D-023: Worker container deferred from phase 1 to phase 3 (supersedes the PLAN phase 1 item)
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** no `worker` service yet.
- **Why:** the user's phase 1 service list (postgres, mailpit, backend, frontend) doesn't include it, and a heartbeat-only stub proves nothing. Phase 3 adds it together with the outbox dispatcher it exists for. PLAN.md updated.

### D-024: Python direct deps pinned exactly; transitive deps not locked (yet)
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** `requirements*.txt` pin direct deps with `==`. npm is fully locked via `package-lock.json`.
- **Why:** this is the boring option. A full Python lock (pip-tools/uv) is extra tooling. **Known gap:** a transitive release could change behaviour between builds. Listed in the README. Revisit in phase 9.

### D-025: Frontend toolchain versions: React 19, Vite 8, Vitest 5, TypeScript 6.0 (supersedes "React 18" in phase-0 ARCHITECTURE §3)
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** the current stable releases, except TypeScript is held at 6.0.x.
- **Why:** React 19 is the current stable line, and nothing we use differs from 18. typescript-eslint 8.71 supports `typescript <6.1`, so TS 7 would break linting. TS 6 defaults `types` to `[]`, so `tsconfig` lists `vite/client` explicitly.

### D-026: All tests and linters run in containers via make
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** `backend-test` (backend `dev` image, source bind-mounted) and `frontend-test` (frontend `test` stage) live under compose profile `test`. `package-lock.json` is generated in `node:22-alpine`.
- **Why:** reviewers need only Docker + make. Host Node (20.20 / npm 10.8) crashed during `npm install` with an internal arborist error, which is exactly the host drift containers avoid.
- **Detail:** pytest runs with `-p no:cacheprovider`, and the ruff/mypy caches live in `/tmp`, because the container user (uid 10001) can't write to the bind-mounted host directory.

### D-027: Smoke test = real `make up` in an isolated compose project
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** `scripts/smoke_compose.sh` sets `COMPOSE_PROJECT_NAME=eventreg-smoke-<pid>` and ports 18080/18000/18025/15433/11025, runs `make up`, makes 7 probes, and always tears down (`down -v --rmi local`). `SMOKE_NO_CACHE=1` rebuilds images without the build cache.
- **Why:** this proves "boots from scratch" (fresh volume, so migrations and the DB init script run from zero) without destroying the developer's stack or data.
- **Evidence it matters:** the first run caught a real bug that unit tests missed. The `alembic` CLI couldn't import `app` (pytest added the path, the CLI didn't). Fixed with `prepend_sys_path = .` in `alembic.ini`.

### D-028: Compose project name `eventreg`; Postgres host port 5433
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** top-level `name: eventreg`. DB published on 5433, because 5432 commonly clashes with a local Postgres. All host ports are overridable in `.env`.

### D-029: Test DB = `<POSTGRES_DB>_test`, created by `infra/db/init-test-db.sh`; suite is destructive by design
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** a shell init script (not `.sql`) so the name follows `POSTGRES_DB`. The suite downgrades to base and upgrades at session start, truncates per test, and **refuses** any DB whose name doesn't end in `_test`.
- **Why:** each test starts from a known state, and a mis-set env var can't wipe the dev DB.
- **Caveat:** the init script only runs on first volume creation. Existing volumes from before this phase need `make clean`.

### D-030: Schema drift is a test failure
- **When:** 2026-10-11T10:10:04+06:00
- **Decision:** `test_models_match_migrations` runs Alembic `compare_metadata` against the migrated test DB and requires zero diffs.
- **Why:** hand-written migrations (D-002) plus ORM models are two sources of truth, and this test keeps them aligned. Mutation-checked: adding a model-only column or removing the partial unique index from the migration makes it fail.

---
<!-- Phase 2 -->

### D-031: Phase 2 plan approved, with its three scoped decisions
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** the user approved (via a question in the phase 3 request) building phase 2 as planned, then phase 3, as separate commits. Approved scope:
  - (a) Events are create, read and update only, with **no DELETE**. Removal = "cancel event" (phase 6, ARCHITECTURE E27). `PATCH` rejects `starts_at` (reschedule is its own endpoint, phase 6).
  - (b) Concurrency tests run in-process: ASGI app, N real Postgres connections. The multi-process HTTP stress test stays in phase 8.
  - (c) Outbox rows are written from phase 2 on. Sending starts in phase 3.

### D-032: Services own their transactions; register retries once on the unique-index backstop
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** service functions take the sessionmaker and open `async with sm() as s, s.begin()` themselves. `register` catches an `IntegrityError` on `uq_registrations_active_email` (logged at ERROR, because the lock should make it unreachable), re-reads, and returns the existing row as a duplicate.
- **Why:** the transaction boundary *is* the correctness unit (lock to commit), so it belongs next to the logic, not in the route. A retry after a constraint error needs a fresh transaction anyway.

### D-033: Concurrency tests prove the race via pg_locks ("lock gate")
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** `tests/concurrency.py`: a separate connection holds `FOR UPDATE` on the event. N requests are fired. The test polls `pg_locks`/`pg_stat_activity` until N backends are blocked, then releases.
- **Why:** `asyncio.gather` alone doesn't guarantee overlap. With the gate, "at the same moment" is a verified fact.
- **Pitfall found:** `pg_stat_activity` is snapshotted once per transaction, so polling must run in AUTOCOMMIT. Otherwise the poller sees a stale snapshot (it first reported 1/20 waiters while all 20 were actually blocked).

### D-034: Only ASCII email addresses are accepted
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** reject non-ASCII addresses with `invalid_email`.
- **Why:** Python's `str.lower()` and Postgres `lower()` (collation-dependent) can disagree on non-ASCII letters. That would violate the `email_normalized = lower(email_normalized)` CHECK, or let two spellings of one address bypass the uniqueness rule. SMTPUTF8 addresses are rare. Correctness wins over coverage here.

### D-035: Ticket-code collisions are retried inside a SAVEPOINT
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** insert in `begin_nested()`. On `uq_registrations_ticket_code`/`uq_registrations_manage_token`, regenerate (up to 5 tries).
- **Why:** a collision mustn't abort the outer transaction or drop the event lock. Tested by forcing collisions (`test_code_collision_retries`).

### D-036: Accepted trade-off: duplicate registration reveals that an email is registered
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** a repeat registration returns 200 with the existing status (and waitlist position), but never the ticket or token.
- **Why:** the brief requires idempotent re-registration, and telling the user "you're already in" is the useful behaviour. Leaking registration status for an email is low impact. There's no rate limiting (out of scope, README).

### D-037: Waitlist email states the position at the time of joining
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** the `waitlisted` email says "#N on the waitlist". The live position is on the manage page (`GET /api/registrations/{token}`).
- **Why:** emailing everyone on every queue change would be spam.

### D-038: The canceller gets a `cancelled` confirmation email
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** dedupe key `cancelled:{registration_id}`, enqueued with the cancellation (already listed in ARCHITECTURE 4.5).

### D-039: `app.main.app` is built lazily (module `__getattr__`)
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** `uvicorn app.main:app` still works, but importing `app.main` (tests, tools) no longer constructs `Settings()`, which now has required secrets. Alembic reads `DATABASE_URL` directly, so the `migrate` service needs no app secrets.

### D-040: Evidence that the lock is load-bearing, and that the DB backstop works on its own
- **When:** 2026-10-11T14:46:03+06:00
- **Decision/result:** mutation run with `.with_for_update()` removed from `lock_event`: 3/6 concurrency tests fail (20-for-5, 100-for-10, last-seat). **Every** failure was `CheckViolation ck_events_seats_taken_range`: the DB refused to overbook, so the requests errored (500) instead of producing a wrong state. The same-email test still passed thanks to the partial unique index. Both layers work independently. The lock is required for *correct answers*, and the constraints guarantee *no corrupt state*.

### D-041: Test app pool = 40 + 10 overflow connections
- **When:** 2026-10-11T14:46:03+06:00
- **Decision:** `make_settings` in tests sets `db_pool_size=40`, so 20 gated requests truly hold 20 connections at once (verified by the gate). Production default stays 10 + 20 per process.

---
<!-- Phase 3 -->

### D-043: Email delivery is at-least-once (user decision); "exactly once" applies to enqueue
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** the user chose at-least-once over at-most-once and over a Mailpit-only "check before resend" trick. A row becomes `sent` only after SMTP accepted it.
- **Why:** over SMTP, "crash after the server accepted, before our commit" can't be made exactly-once. One side must give: a duplicate or a lost ticket. A duplicate (with the same Message-ID) is the lesser harm.
- **Proof:** no duplicates on graceful restart, on a crash before send, or with concurrent workers (tests). The window itself is demonstrated by `test_known_window_crash_after_smtp_accept_resends_same_message_id`, and bounded to ≤1 per real SIGKILL by `test_sigkill_mid_batch_then_restart_delivers_all_at_most_one_duplicate`.

### D-044: `attempts` doubles as the claim's fencing token
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** the claim increments `attempts`. Completion statements require `status='sending' AND attempts=:token`.
- **Why:** without it, a worker whose lease expired could, after a re-claim, flip the row back to `pending` (late failure report), and a third worker would send it again. No schema change was needed.
- **Evidence:** removing the fence makes `test_stale_claim_cannot_overwrite_newer_claim` fail. The first version of that test did *not* catch the mutant, because it reported after the new owner had finished and the status check alone protected the row. It was rewritten to report while the new owner is still sending.

### D-045: Graceful shutdown releases the unsent rest of a batch; `attempts` counts claims
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** on SIGTERM the in-flight message completes and is recorded, and the remaining claimed rows go back to `pending` (fenced). `attempts` isn't decremented.
- **Why:** `docker compose restart worker` or a deploy must not wait out a lease, and must not create duplicates. Not decrementing keeps the fencing token monotonic. The cost is that a release uses up one of 8 attempts, which is acceptable.

### D-046: The worker refuses to start if lease ≤ worst-case batch send time
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** `OUTBOX_LEASE_SECONDS > OUTBOX_BATCH_SIZE × (SMTP_TIMEOUT_SECONDS + OUTBOX_SEND_INTERVAL_SECONDS)`, otherwise `ValueError` at startup.
- **Why:** if a slow but alive worker's lease expires mid-batch, another worker would send the same rows. Defaults are 10 × (10 + 0) = 100s < 120s.

### D-047: Concurrency tests for claims use a table-lock gate
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** `test_concurrent_claims_are_disjoint` holds `LOCK TABLE email_outbox IN SHARE MODE` (which blocks the claim UPDATEs), waits until 10 claimers are blocked in pg_locks, then releases them.
- **Why:** the ungated two-dispatcher test passed even with `FOR UPDATE SKIP LOCKED` removed, because the claims never actually overlapped. With the gate, the mutant fails ("a row was claimed by two dispatchers").

### D-048: Tests use a separate Mailpit (`mailpit-test`, profile test)
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** tests empty and read only `mailpit-test`. The dev `mailpit` is never touched by tests.
- **Why:** `make test` must never delete the emails a developer is looking at, and dev traffic must not pollute assertions.

### D-049: Worker liveness via heartbeat file
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** the dispatcher loop touches `WORKER_HEARTBEAT_FILE` each iteration, and the compose healthcheck fails if it's older than 30s. `make up --wait` therefore also waits for the worker.
- **Why:** "process is running" isn't the same as "loop is alive". A stuck loop is detected without an HTTP server in the worker.

### D-050: `OUTBOX_SEND_INTERVAL_SECONDS` (default 0)
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** an optional pause between sends.
- **Why:** real SMTP providers rate-limit. The process tests also use it (0.2s) so a SIGTERM or SIGKILL reliably lands mid-batch. It's included in the lease rule (D-046).

### D-051: "Unguessable" ticket code: 40 bits from `secrets`, plus check-in is organizer-only
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** keep 8 Crockford symbols (D-013) rather than lengthening the code that staff type.
- **Why:** the code isn't a credential. Check-in requires the organizer cookie and is scoped per event. The probability that one blind guess hits any of 1,000 valid codes is 1000/2^40 ≈ 9×10⁻¹⁰. Participant control (view/cancel) uses a separate 256-bit `manage_token`. Uniqueness: DB unique constraint plus SAVEPOINT retry (D-035).

### D-052: Messages are rendered at enqueue time; plain text only
- **When:** 2026-10-11T15:17:52+06:00
- **Decision:** subject and body are stored in the outbox row (auditable, testable, and they don't change if the event is edited later). No HTML part.
- **Why:** boring and reliable. Mailpit shows text fine. The reschedule (phase 6) sends a new email instead of mutating queued ones.

### D-053: The registration response says the ticket is "on its way", not "was sent"
- **When:** 2026-10-11T15:17:52+06:00
- **Why:** at response time the email is only queued. During the Mailpit outage demo, "was sent" would have been false.

---
<!-- Phase 4 -->

### D-054: Check-in = one conditional UPDATE, with no event lock
- **When:** 2026-10-11T19:56:24+06:00
- **Decision:** `UPDATE registrations SET status='checked_in' … WHERE event_id AND ticket_code AND status='confirmed' RETURNING …`. Only when 0 rows are updated is the row re-read, purely to choose the error. The event row is read without a lock, only to reject cancelled events.
- **Why:**
  - Check-in doesn't change seat ownership (a checked-in person keeps the seat), so it never touches `seats_taken` and doesn't need the per-event lock.
  - A crowd at the door doesn't queue behind registrations. 30 parallel check-ins of different tickets all succeed (tested).
  - The unlocked event read is safe: event cancel (phase 6) doesn't modify registration rows, so a check-in that commits concurrently is equivalent to "checked in just before the cancel".
- **Evidence:**
  - 10 gated scanners × 10 rounds gave exactly 1 success each round.
  - Removing `status='confirmed'` from the UPDATE fails 6 tests, one of them via the DB constraint `ck_registrations_cancelled_has_time`.

### D-055: Distinct check-in error codes `ticket_cancelled` and `ticket_waitlisted` (supersedes `ticket_not_active`, API.md / ARCHITECTURE E20)
- **When:** 2026-10-11T19:56:24+06:00
- **Decision:** two 409 codes instead of one generic code with `details.status`. All check-in errors: `invalid_code_format` (422), `ticket_not_found` (404, also used for a code from another event), `already_checked_in` (409, with the original time and email), `ticket_cancelled` (409), `ticket_waitlisted` (409), `event_cancelled` (409).
- **Why:** the user asked for clear codes per case. Door staff UI (phase 7) maps each to a distinct message without parsing details.

### D-056: Stats come from a single SQL statement (one snapshot); contract adds `registered` and `emails.sending`
- **When:** 2026-10-11T19:56:24+06:00
- **Decision:** one statement with `count(*) FILTER` plus scalar subqueries for email counts. `registered = confirmed + checked_in`, `seats_left = capacity − registered`.
- **Why:** separate queries could observe a half-applied transition between them (e.g. a cancellation without the matching promotion). One statement = one MVCC snapshot = numbers that always satisfy the invariants, verified by sampling stats during 40 parallel writes. `registered` is the brief's word. `sending` exists in the outbox, so hiding it would make the counts not add up.
- **Note:** `confirmed` means "holds a seat, not arrived". The UI must label it that way.

### D-057: One timestamp wire format everywhere, including error details
- **When:** 2026-10-11T19:56:24+06:00
- **Decision:** `app/timefmt.iso_utc` (UTC, `Z`), used by response schemas and by the error envelope encoder.
- **Why:** found by a test. `already_checked_in.details.checked_in_at` was serialized as `+00:00` while the success body used `Z`. Clients compare these strings.

### D-058: Check-in is done by the organizer login (assumption A1 unchanged)
- **When:** 2026-10-11T19:56:24+06:00
- **Decision:** `POST /api/admin/events/{id}/checkin`, `/stats` and `/registrations` sit behind the same signed-cookie organizer auth as the other admin endpoints. There's no separate door-staff role.
- **Why:** this is the auth model decided in ARCHITECTURE (A1, D-011). A staff role would be the first thing to add if the organizer password is shared too widely.

### D-059: Race tests choose the winner deterministically via the lock queue
- **When:** 2026-10-11T19:56:24+06:00
- **Decision:** for check-in vs cancel, the test starts one request, waits until it's blocked on the gated row, then starts the other. Postgres grants the row in queue order, so both outcomes (check-in wins / cancel wins) are asserted explicitly instead of "someone won".
- **Why:** a test that accepts either outcome can't detect a wrong outcome.

---
<!-- Phase 5 -->

### D-060: Two SSE streams: public "availability" and organizer "stats" (refines D-010 / API.md single public stream)
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:**
  - `GET /api/events/{id}/stream` (public): `event_id, status, starts_at, capacity, seats_left, waitlist_count`.
  - `GET /api/admin/events/{id}/stream` (organizer cookie): the full `/stats` body plus `event_id`.
- **Why:** you asked for both. The public page needs only availability. Attendance (`checked_in`) and email delivery numbers are organizer information. Because only changed snapshots are sent, a check-in produces no public frame.

### D-061: SSE tests run against real uvicorn processes, never the in-process ASGI transport
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:** a module-scoped fixture starts three servers on the test DB: two single-worker servers (`a`, `b`) for deterministic cross-process checks, and one `--workers 2` server exactly like compose. Writes come from the test's in-process app, a separate process.
- **Why:**
  - `httpx.ASGITransport` buffers the whole response, so it can't test an endless stream.
  - With separate processes, an update can only arrive through Postgres LISTEN/NOTIFY, never through shared memory.
  - The `--workers 2` test proves streams were held by **both** pids via an `X-Backend-Pid` header. That header is added by a pure-ASGI middleware only when `APP_ENV != production`, because `BaseHTTPMiddleware` is known to interfere with streaming and disconnects.

### D-062: The listener reconnects and resyncs; signals carry only the event id
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:** the broker's LISTEN connection reconnects after 1s and then wakes **every** subscriber. Notifications carry only the event id, and each stream re-reads its snapshot.
- **Why:** NOTIFYs sent while no one listens are gone. Re-reading after reconnect makes those gaps harmless. Tested by `pg_terminate_backend` on all LISTEN connections followed by an immediate write. A mutation without the resync fails that test 3/3 times.

### D-063: Email completions notify; claims don't
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:** the dispatcher's fenced completion (sent / retry / failed / released) calls `pg_notify` in the same transaction. The claim (`pending → sending`) doesn't.
- **Why:** email counts are part of the organizer stats, so the final outcome must show up live. Notifying on every claim would double the traffic for a transient state the organizer doesn't act on.

### D-064: Organizer streams close when the login expires
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:** the expiry is computed from the signed cookie timestamp at connect. When reached, the stream sends `event: session_expired` and ends.
- **Why:** otherwise a stream opened just before the 12h expiry would keep delivering organizer data indefinitely. Tested with `SESSION_MAX_AGE_SECONDS=2`.

### D-065: Uvicorn `--timeout-graceful-shutdown 5`
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:** set in the backend image's CMD.
- **Why:** SSE responses never finish on their own. Without a limit, `docker compose restart backend` waits for every open browser tab. Clients reconnect automatically (`retry: 3000`) and get a fresh snapshot.

### D-066: No `Last-Event-ID` replay
- **When:** 2026-10-12T02:14:10+06:00
- **Decision:** frames carry no `id:`. A reconnect gets the current snapshot.
- **Why:** the client needs current state, not history. Replay would need a per-event change log, which is extra state that can disagree with the tables.

---
<!-- Phase 6 -->

### D-067: Scheduler = per-event `FOR UPDATE SKIP LOCKED` + outbox dedupe key (refines D-008)
- **When:** 2026-10-12T02:47:37+06:00
- **Decision:** each tick repeatedly takes the next due event that still lacks a reminder for its current version (`… FOR UPDATE OF e SKIP LOCKED`, one event per transaction), enqueues its reminders, and commits. The key is `reminder:{event}:v{schedule_version}:{email}`. There are no in-memory timers. The worker process runs the scheduler next to the dispatcher, and compose health checks both heartbeats.
- **Why:**
  - Holding the event lock means register, cancel and reschedule can't change the confirmed set or version mid-enqueue.
  - SKIP LOCKED lets 3+ instances work in parallel without waiting on each other.
  - A crash before commit rolls back cleanly.
- **Honest detail found by a test:** SKIP LOCKED is **not** what makes it exactly-once. Under READ COMMITTED an instance can visit an event another instance finished a moment earlier (its query snapshot predates that commit, and the lock was already released). Its insert then conflicts and enqueues nothing. The unique key is the guarantee. The test now asserts "each event's reminders enqueued by exactly one instance", not "visited by one".

### D-068: Reminders are re-checked and re-rendered at send time; skipped ones can be re-armed
- **When:** 2026-10-12T02:47:37+06:00
- **Decision:** before sending a `reminder`, the dispatcher checks four things: the event is scheduled, it has the same `schedule_version`, `now < starts_at`, and the **person** (by `email_normalized`) is still `confirmed`. Otherwise the row becomes `skipped` with the reason in `last_error`. Content is re-rendered from current data (ticket code, manage link, date). The scheduler's upsert re-arms a `skipped` row (`DO UPDATE … WHERE status='skipped'`) if the person is confirmed again inside the window. `sent`/`pending`/`failed` rows are never touched.
- **Why:** the reminder must be true when it arrives (not stale after cancel, reschedule, check-in, start, or event cancel). Re-arming keeps "every confirmed participant gets one" true for someone who cancels and re-registers before the reminder went out, while "at most one sent per person per date" still holds.
- **Evidence:** mutants without the version check or without the re-arm each fail a dedicated test.

### D-069: Reschedule and event-cancel emails also go to checked-in people (extends A5)
- **When:** 2026-10-12T02:47:37+06:00
- **Decision:** recipients = confirmed + waitlisted + checked_in. Cancelled people are excluded.
- **Why:** someone who already arrived is clearly a participant (the brief: "every participant gets an email"). It only happens if the organizer moves or cancels after check-ins started.

### D-070: Use `RETURNING` to know what an `INSERT … ON CONFLICT` wrote; `rowcount` is unreliable here
- **When:** 2026-10-12T02:47:37+06:00
- **Decision:** both the scheduler's upsert and `emails.outbox.enqueue` count `RETURNING id` rows.
- **Why:** verified empirically. Through the ORM `AsyncSession`, `insert(...).on_conflict_…` reports `rowcount = -1` whether or not a row was written (textual SQL reports correctly). The scheduler test exposed it, because a conflicting revisit was counted as "enqueued". Phase 2's `enqueue()` had the same latent bug: its return value was always truthy. No caller used it, so behaviour was unaffected. It's fixed and pinned by `test_enqueue_reports_whether_a_row_was_written`.

### D-071: Rescheduling a started event to a future time reopens it
- **When:** 2026-10-12T02:47:37+06:00
- **Decision:** allowed as long as the event isn't cancelled and the new time is in the future. Registration (open while `now < starts_at`) reopens.
- **Why:** "the event had to be moved after doors opened" is a real case. Refusing would force the organizer to cancel and recreate, losing all registrations.

### D-072: Known race, accepted: a reminder already handed to SMTP when a reschedule commits
- **When:** 2026-10-12T02:47:37+06:00
- **Decision:** the send-time check covers a reminder claimed *before* the reschedule (tested). It can't cover the instant after the check passed and while SMTP is transmitting. That message carries the old date, and the "New date" email follows right after.
- **Why:** closing it would need a lock across the SMTP call, which would block the reschedule on a mail server. The window is milliseconds and the outcome is corrected by the next email.

---
<!-- Phase 7 -->

### D-073: Frontend structure: React Router v8 declarative routes, one API client, no state library
- **When:** 2026-10-12T03:24:56+06:00
- **Decision:**
  - `App.tsx` holds the full route table (`AppRoutes`, also used by tests).
  - `api.ts` is the only module that calls `fetch`. It turns every failure into `ApiError(status, code, details)`, including network errors (`network_error`).
  - `errors.ts` maps codes to sentences.
  - Pages keep local `useState`. Organizer pages sit behind `RequireOrganizer` (asks `/api/admin/me`; 401 → login with `?next=`, and only `/admin…` targets are accepted, so there's no open redirect).
- **Why:** a handful of pages doesn't justify Redux or React Query. A single client keeps error handling uniform. React Router 8 is current, and its exports were checked before use.

### D-074: Cancel happens on the ticket page (`/r/:token`), never on the public event page
- **When:** 2026-10-12T03:24:56+06:00
- **Decision:** the event page explains "use the link in your email". The ticket page has the cancel button behind a `confirm()`.
- **Why:** cancelling by typing an email would let anyone cancel anyone (A3/D-012). The brief's "cancel via ticket" maps to the emailed capability link.

### D-075: `useEventStream`: state keyed by URL, last snapshot stays visible while reconnecting
- **When:** 2026-10-12T03:24:56+06:00
- **Decision:**
  - Status values: connecting / live / reconnecting / expired / closed.
  - On a network error the last numbers stay on screen, marked "reconnecting…", and the browser's EventSource retries by itself.
  - A server refusal (401/404) gives `closed`. `session_expired` closes the stream and shows "log in again".
  - State is stored together with its URL, so switching events never shows another event's numbers. This also satisfies the React rule against synchronous `setState` in effects, which the linter flagged in the first version.
  - The dashboard re-fetches the participant list on every stats frame.

### D-076: Times: entered as `datetime-local` in the browser's zone, sent as UTC ISO, shown in the browser's locale
- **When:** 2026-10-12T03:24:56+06:00
- **Decision:** `fromLocalInput()` gives `new Date(value).toISOString()`. Display uses `toLocaleString`. Labels say "(your local time)".
- **Why:** the API requires timezone-aware instants (naive times get 422). Organizer and participants each see their own local time. A per-event timezone stays out of scope (ARCHITECTURE §7).

### D-077: Component tests render the real routes against a mocked API and a fake EventSource
- **When:** 2026-10-12T03:24:56+06:00
- **Decision:** `test/render.tsx::renderAt(path)` uses `MemoryRouter` + `AppRoutes`. `test/fakes.ts` provides a `mockApi` route table (records calls and bodies) and a `FakeEventSource` (`emit` / `fail` / `open`).
- **Why:** tests exercise what a user does (labels, buttons, alerts), not internals. The real backend plus real browser is phase 8 (Playwright). Phase 7 includes a manual two-tab walkthrough on the real stack (DEVLOG).

### D-078: Door-screen behaviour
- **When:** 2026-10-12T03:24:56+06:00
- **Decision:** the input is autofocused and Enter submits. On success: big green "Welcome!", email and time, input cleared, focus kept. On error: big red title per code (Already used + time, Ticket cancelled, No seat (waitlist), Unknown code, Not a ticket code), input text selected for quick correction. There's a live "N / M arrived" counter.
- **Why:** typing replaces a scanner (brief). Staff must read the result from a distance and move on to the next person without touching the mouse.

---
<!-- Phase 8 -->

### D-079: E2E = Playwright in its official image, against an isolated compose stack
- **When:** 2026-10-12T03:53:20+06:00
- **Decision:** `scripts/e2e.sh` starts project `eventreg-e2e` (own ports, volumes, `SCHEDULER_TICK_SECONDS=2`) from `down -v`. It runs `mcr.microsoft.com/playwright:v1.64.0-noble` with `@playwright/test` 1.64.0 (version-matched) on the compose network (`BASE_URL=http://frontend`, that stack's Mailpit), then tears everything down. Settings: Chromium, 1 worker, **0 retries**, browser timezone UTC. Every test uses its own event and emails.
- **Why:** real browsers, the real nginx → 2 workers → Postgres path, real SMTP. The developer's stack is never touched. Retries would hide flakiness. Manage links from emails are opened by *path*, because the link host (`PUBLIC_BASE_URL`) is the developer-facing URL, not the in-network one.

### D-080: "Two tabs" = two browser contexts; "no reload" is asserted, not assumed
- **When:** 2026-10-12T03:53:20+06:00
- **Decision:** each tab is its own `browser.newContext()` (separate cookies and storage, like two people). The organizer contexts get the login cookie from an API login. Live tests mark `window` before the change and assert the marker survives, which proves the same document updated.
- **Honest limit:** the last-seat race through the UI fires two clicks via `Promise.all`. They overlap closely but aren't *proven* simultaneous. Proven simultaneity lives in the gated pytest tests (pg_locks). The UI test proves both outcomes are rendered correctly (3 rounds).

### D-081: `scripts/stress.py` checks invariants through the API, over HTTP, against the multi-worker stack
- **When:** 2026-10-12T03:53:20+06:00
- **Decision:** 200 distinct + 10×5 duplicate (case/space variants) registrations at once on a 50-seat event. Then 20 cancels (manage links from the real ticket emails in Mailpit) + 30 registrations at once. 17 invariants, exit 1 on any violation. It runs in `make stress` (dev stack) and in `make proof` (E2E stack).
- **Result recorded:** about 113–118 req/s for one event, p95 about 2.1s with 250 requests in flight. That's the cost of serializing an event's seat changes on its row lock (D-003). Different events don't contend. Accepted for this scale and documented in the README.

### D-082: `make proof` derives the requirement table from JUnit results; TEST_PLAN is machine-checked
- **When:** 2026-10-12T03:53:20+06:00
- **Decision:** `scripts/proof.sh` runs lint, backend (JUnit), frontend (JUnit), concurrency loop (N=5), smoke, E2E (JUnit) and stress, continuing after failures. `scripts/proof_report.py` resolves every reference in `docs/TEST_PLAN.md` (`file::name`, `::name`, params, `<placeholders>`, step words) and marks each row PASS / FAIL / MISSING / MANUAL. Any FAIL or MISSING makes the proof fail.
- **Why:** the brief asks for proof and an honest README. A hand-written "all green" table can drift. This one can't claim a test that doesn't exist, which was verified with a fake plan containing bogus names (they show as MISSING). P7 (honest README) is the only MANUAL row.

### D-083: Test reports in `reports/` (gitignored, mode 777)
- **When:** 2026-10-12T03:53:20+06:00
- **Decision:** containers running as different users (backend uid 10001, node/playwright root) write JUnit/JSON there.
- **Why:** simplest way to collect results without host tooling. Permissions only matter on the developer machine.

### D-084: E2E mutation evidence
- **When:** 2026-10-12T03:53:20+06:00
- **Decision/result:** a frontend-only regression (event page ignores live data) passes every backend test but fails 2 E2E tests: the live seat counter in tab B, and the new date shown live after a reschedule. The other 7 correctly still pass. Restored.
