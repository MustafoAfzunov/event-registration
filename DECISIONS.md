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
