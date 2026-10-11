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
