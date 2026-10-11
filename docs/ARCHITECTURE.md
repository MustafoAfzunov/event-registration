# Architecture — Event Registration Service

Status: **design only (phase 0)**. Nothing here is implemented yet. Each section says which phase builds it.

## 1. Requirement clarifications and assumptions

The brief leaves some points open. These are the assumptions we work from. Each one is also logged in `DECISIONS.md` and can be revisited.

| # | Ambiguity | Assumption |
|---|-----------|------------|
| A1 | "Organizer": one person or many accounts? | A **single organizer role** protected by a shared password from env (`ORGANIZER_PASSWORD`). There are no user accounts. Door staff for check-in use the same login. |
| A2 | One event or many? | **Many events** are supported. It costs almost nothing extra and keeps the organizer screen generic. The UI is still simple: a list, then one event. |
| A3 | How does a participant cancel? | With a **secret manage link** (`/r/{manage_token}`) sent in every email. Cancelling "by email address" alone would let anyone cancel anyone. |
| A4 | Who is a "participant" for reminders? | Only seat holders (`confirmed`) get the **reminder**. Waitlisted people have no seat, so a "see you tomorrow" email would mislead them. |
| A5 | Who is a "participant" for reschedule emails? | **confirmed + waitlisted** both get the reschedule email, because the date change affects whether they still want to wait. Cancelled people don't. |
| A6 | "Exactly one reminder 24h before" | Exactly one reminder **per person per event schedule**. If the event is rescheduled, the old reminder becomes void and one new reminder is due for the new time (see §4.5). If someone gets a seat when the event is already less than 24h away, they get their reminder on the next scheduler tick. |
| A7 | When does registration close? | At `starts_at`. After that, register, cancel and capacity changes are rejected. |
| A8 | Check-in window | Check-in is allowed any time while the event is `scheduled`, with no time window. The event has no end time, so we don't invent one. |
| A9 | Does the registration API return the ticket? | **No.** The ticket code and manage link are delivered **only by email**. If the API returned them, anyone who typed someone else's email would get that person's ticket (the duplicate-registration path makes this obvious). The API returns only status and waitlist position. |
| A10 | Email normalization | Trim, then lowercase the **whole address**, and validate syntax with `email-validator` (no DNS lookup). **ASCII addresses only** (D-034): Python and Postgres `lower()` can disagree on non-ASCII letters. We do **not** strip Gmail dots or `+tags`, because those rules belong to one provider. The address as entered is kept for display. |

## 2. System overview

```
 Browser tab(s)                 docker compose network
 ┌───────────────┐   HTTP    ┌──────────────────┐   proxy /api   ┌──────────────────────┐
 │ React (Vite   │──────────▶│ frontend (nginx) │───────────────▶│ backend: FastAPI      │
 │ build)        │◀── SSE ───│ static + proxy   │◀───────────────│ uvicorn --workers 2   │
 └───────────────┘           └──────────────────┘                └──────────┬───────────┘
                                                                  SQL + LISTEN/NOTIFY
                                                                             │
 ┌──────────────┐  SMTP   ┌─────────────────────────┐   SQL       ┌──────────▼───────────┐
 │ Mailpit      │◀────────│ worker: outbox sender + │────────────▶│ PostgreSQL 16         │
 │ :1025 / :8025│         │ reminder scheduler      │             │ (source of truth)     │
 └──────────────┘         └─────────────────────────┘             └──────────────────────┘
```

Compose services: `db` (postgres:16), `mailpit`, `migrate` (one-shot `alembic upgrade head`), `backend` (API, 2 uvicorn workers), `worker` (outbox dispatcher and scheduler), `frontend` (nginx serving the Vite build and reverse-proxying `/api` to `backend:8000`).

The frontend and backend are separate containers that talk over the compose network. The browser sees a single origin (`http://localhost:8080`), so there's no CORS and the organizer session cookie stays simple. In dev, the Vite dev server proxies `/api` the same way. The backend is also exposed on `:8000` so it can be called directly.

**Why two uvicorn workers by default:** this keeps "live updates across multiple backend workers" exercised all the time, so it can't silently break. A single worker would hide fan-out bugs.

## 3. Technology choices (each justified)

| Area | Choice | Why |
|------|--------|-----|
| API framework | **FastAPI** + Pydantic v2 | Required by the brief. Pydantic gives typed request validation and the OpenAPI schema for free. |
| Sync vs async | **Async** end to end (async SQLAlchemy, async SMTP) | SSE holds a connection open per tab, which costs a thread under sync code but is cheap as an asyncio task. Mixing sync DB calls into async handlers is a common source of event-loop stalls, so we stay async. |
| DB driver | **psycopg 3** (async) | A single driver serves async SQLAlchemy, sync Alembic and `LISTEN/NOTIFY` (`AsyncConnection.notifies()`). That means one dependency with one set of behaviours to learn. |
| ORM | **SQLAlchemy 2.0** (Core-style queries via ORM models) | Mature and explicit, and it supports `with_for_update()`, `RETURNING`, `ON CONFLICT` and partial indexes directly. We write the critical concurrency statements as explicit SQL expressions, not hidden ORM magic. |
| Migrations | **Alembic**, hand-reviewed autogenerate | The standard for SQLAlchemy. Partial unique indexes and CHECK constraints get written by hand in migrations because autogenerate misses some of them. |
| Isolation level | **READ COMMITTED + explicit row locks** | `SELECT … FOR UPDATE` on the event row is easy to reason about and needs no retry loop. SERIALIZABLE would also be correct, but every caller would need serialization-failure retries. |
| Background work | One **`worker` process** with two asyncio loops: outbox dispatcher and reminder scheduler | We need no broker. Postgres is the queue (`FOR UPDATE SKIP LOCKED`), and the scheduler is a stateless periodic scan that is idempotent by construction. Celery would need Redis/RabbitMQ, and APScheduler keeps jobs in memory or adds its own job store, which is one more source of truth. |
| Email delivery | **Transactional outbox** table and SMTP to Mailpit via `aiosmtplib` | The email intent is committed in the same transaction as the seat change. A crash or a Mailpit outage can never produce "seat given, email lost" or "email sent, seat rolled back". |
| Live updates | **SSE** (`text/event-stream`) | The data flow is server→client only. `EventSource` reconnects automatically, it's plain HTTP through nginx, and it needs no extra library. WebSockets would add a bidirectional protocol we don't need. |
| Cross-worker fan-out | **Postgres `LISTEN/NOTIFY`** | Every API process listens on one channel. `pg_notify` is sent inside the writing transaction and delivered only on commit, so clients never see uncommitted state. This adds no Redis. |
| Organizer auth | Password → **signed httpOnly cookie** (`itsdangerous`), `SameSite=Strict` | `EventSource` can't send an `Authorization` header, so a cookie fits. Putting the token in the query string would leak it into logs. With a single origin, SameSite=Strict plus JSON-only bodies covers CSRF for this scope. |
| Participant auth | **Capability tokens**: `manage_token` (32 bytes, urlsafe) in the emailed link | Participants have no accounts. Whoever holds the link controls the registration, the usual pattern for event tickets. |
| Ticket code | 8 chars of Crockford base32 (≈40 bits), shown as `ABCD-EFGH` | It's short enough to type at the door. Input normalization ignores case, spaces and dashes, and maps O→0, I/L→1. A unique index catches collisions, and insert retries on conflict. |
| Frontend | **React 19 + Vite 8 + TypeScript 6.0**, React Router, plain `fetch` | Required by the brief. With no state library, the app is a handful of pages and hooks. |
| Tests (backend) | **pytest + pytest-asyncio + httpx.AsyncClient**, against **real Postgres** | Locking semantics can't be tested on SQLite or with mocks. Concurrency tests use separate DB connections. |
| Tests (frontend) | **Vitest + Testing Library** | Native to Vite. |
| E2E | **Playwright** against the full compose stack, reading emails from the Mailpit API | It proves the real system: two browser contexts (the "two tabs"), real SMTP and real SSE. |
| Lint/format | `ruff` (py), `eslint` + `prettier` (ts), `mypy --strict` on `app/` | Cheap, catches whole classes of bugs. |
| Python deps | `pyproject.toml` + pinned `requirements*.txt` installed with pip | This is the most boring option, and it's reproducible. |

## 4. Mechanisms for the tricky behaviours

### 4.1 Per-event lock: one rule for every seat-changing operation

Every operation that can change **who holds a seat** runs in a single transaction that starts with:

```sql
SELECT * FROM events WHERE id = :event_id FOR UPDATE;
```

These operations are register, cancel, capacity change, reschedule and event cancel. The lock serializes them **per event**, so different events don't contend. **Lock order is always event row, then registration rows**, which rules out deadlocks among these operations. Check-in doesn't change seat ownership, so it doesn't take the event lock (see §4.6).

**Belt and braces at DB level:** `events.seats_taken` is a counter maintained in those same transactions, and it carries `CHECK (seats_taken BETWEEN 0 AND capacity)`. Even if the application logic were wrong, Postgres would refuse to overbook. An invariant test checks that `seats_taken = count(confirmed + checked_in)` after every concurrency test.

### 4.2 Registration and duplicate prevention

Inside the event lock:
1. Reject the request if the event is `cancelled` (409 `event_cancelled`) or `starts_at <= now` (409 `registration_closed`).
2. Look up an **active** registration (`status <> 'cancelled'`) for `(event_id, email_normalized)`. If one exists, **return it unchanged** with HTTP 200 and `created: false`. No new seat, no new email.
3. If `seats_taken < capacity`, insert it as `confirmed`, set `seats_taken += 1`, and enqueue a `ticket` email.
4. Otherwise insert it as `waitlisted` with `queue_seq = nextval('registration_queue_seq')` and enqueue a `waitlisted` email.
5. `pg_notify('event_changed', event_id)`, then commit.

**DB-level guarantee:** a partial unique index
`CREATE UNIQUE INDEX uq_registrations_active_email ON registrations (event_id, email_normalized) WHERE status <> 'cancelled';`
makes a second active row for the same email physically impossible, even under a bug or a lock bypass. If it ever fires (`IntegrityError`), the service re-reads the row and returns it as a duplicate.

### 4.3 Last-seat race

Two requests for the last seat both block on `FOR UPDATE` of the same event row. The first one sees `seats_taken = capacity - 1`, confirms, and commits. The second one wakes up, re-reads the row under READ COMMITTED (it sees the committed `seats_taken = capacity`), and is waitlisted. The outcome is deterministic: exactly one confirmed and one waitlisted. The CHECK constraint is the backstop.

### 4.4 Waitlist promotion (FIFO)

- **Order:** `queue_seq` ascending. It comes from a global Postgres sequence and is assigned **while the event lock is held**, so sequence order equals the order in which requests got onto the waitlist. Ties can't happen because the sequence is unique. Timestamps aren't used for ordering: clocks have finite resolution, and `now()` is the transaction start time, not the commit time.
- **When:** in the **same transaction** that frees a seat (a confirmed person cancels, or capacity goes up):
  ```sql
  SELECT id FROM registrations
  WHERE event_id = :e AND status = 'waitlisted'
  ORDER BY queue_seq LIMIT :free_seats FOR UPDATE;
  ```
  Each promoted row is set to `confirmed`, `seats_taken` is incremented, and a `promoted` email with the ticket is enqueued. Because promotion is atomic with the cancellation, a new registrant can never grab a freed seat ahead of the waitlist.
- **Invariant** (asserted in tests): for a scheduled event, `seats_taken < capacity` implies the waitlist is empty.
- A waitlisted person who cancels just leaves the queue. Nobody is promoted, because no seat was freed.
- `waitlist_position` is computed on read: `1 + count(waitlisted with smaller queue_seq)`.

### 4.5 Emails: transactional outbox, exactly-once enqueue, at-least-once send

**Enqueue.** Business transactions insert rows into `email_outbox` with a deterministic **`dedupe_key`** under a UNIQUE constraint, using `INSERT … ON CONFLICT (dedupe_key) DO NOTHING`:

| kind | dedupe_key | sent to |
|------|-----------|---------|
| `ticket` | `ticket:{registration_id}` | new confirmed registration |
| `waitlisted` | `waitlisted:{registration_id}` | new waitlisted registration |
| `promoted` | `promoted:{registration_id}` | waitlisted → confirmed |
| `reminder` | `reminder:{event_id}:v{schedule_version}:{email_normalized}` | confirmed, in the 24h window |
| `rescheduled` | `rescheduled:{event_id}:v{schedule_version}:{registration_id}` | confirmed + waitlisted |
| `event_cancelled` | `event_cancelled:{event_id}:{registration_id}` | confirmed + waitlisted |
| `cancelled` | `cancelled:{registration_id}` | the person who cancelled (confirmation) |

The reminder key uses **email**, not registration id. Someone who cancels and re-registers therefore still gets only one reminder per schedule version.

Subject and body are rendered **at enqueue time** and stored, which makes them auditable and lets tests assert on them.

**Dispatch** (worker loop, every `OUTBOX_POLL_SECONDS`, default 1s):
```sql
UPDATE email_outbox SET status='sending', locked_until = :now + interval '60 s', attempts = attempts + 1
WHERE id IN (
  SELECT id FROM email_outbox
  WHERE (status='pending' AND next_attempt_at <= :now)
     OR (status='sending' AND locked_until < :now)      -- lease expired: previous worker died
  ORDER BY id LIMIT 20 FOR UPDATE SKIP LOCKED)
RETURNING *;
```
COMMIT, then send each row over SMTP, then mark it `sent` with `sent_at`. On SMTP error the row goes back to `pending` with `next_attempt_at = now + min(5s·2^attempts, 1h)` and `last_error` set. After `OUTBOX_MAX_ATTEMPTS` (default 8) it becomes `failed`. `SKIP LOCKED` makes N worker replicas safe.

**Honest guarantee.** Enqueue is **exactly once**: it's atomic with the state change and deduped by key. SMTP delivery is **at least once**. If the worker crashes after the SMTP server accepts a message but before `sent` is committed, the lease expires and the email is sent again. Exactly-once delivery over SMTP isn't achievable in general. To mitigate, each email carries a `Message-ID: <{dedupe_key-hash}@eventreg.local>`, so a duplicate is identifiable and most clients thread or collapse it. The README will say this plainly.

**Send-time guard (reminders only).** Just before sending a `reminder`, the worker re-checks that the registration is still `confirmed` and that `events.schedule_version` still equals the version in the row. If not, the row is marked `skipped`. This voids stale reminders after a cancellation or reschedule.

**A failing promotion email** never undoes the seat. The DB is the source of truth. The person holds the seat. The email retries with backoff, and permanent failures show up in organizer stats (`emails.failed`) and the worker log.

### 4.6 Check-in atomicity

A single conditional statement does the check-in:
```sql
UPDATE registrations SET status='checked_in', checked_in_at=:now
WHERE event_id=:e AND ticket_code=:code AND status='confirmed'
RETURNING id, email, checked_in_at;
```
If 0 rows come back, the code is looked up again to choose the error: `ticket_not_found` (404), `already_checked_in` (409, includes the original `checked_in_at`), or `ticket_not_active` (409, waitlisted or cancelled). When two staff scan the same code at the same moment, Postgres row locking plus re-evaluating the `WHERE` under READ COMMITTED means exactly one `UPDATE` matches. `pg_notify` is sent in the same transaction.

Check-in racing with cancellation: both are conditional updates on `status='confirmed'`, so exactly one wins. Cancel takes the event lock first and then the row. Check-in takes only the row. That ordering can't deadlock.

### 4.7 Reminders scheduler (restart-safe, catches up after downtime)

The worker loop runs every `SCHEDULER_TICK_SECONDS` (default 30s):
```sql
INSERT INTO email_outbox (...)
SELECT ... FROM registrations r JOIN events e ON e.id = r.event_id
WHERE e.status='scheduled' AND r.status='confirmed'
  AND e.starts_at - :lead <= :now AND :now < e.starts_at
ON CONFLICT (dedupe_key) DO NOTHING;
```
- **Stateless and idempotent.** The outbox `dedupe_key` *is* the "reminder sent" record. Running the tick twice, or on two worker replicas, enqueues nothing new.
- **Restart and downtime.** If the worker was down when the 24h mark passed, the next tick after it comes back still finds those events (`now < starts_at`) and sends late reminders. If the downtime outlasted the event start, **no reminder is sent**, because a reminder after the start is noise. The README documents this.
- **Clock.** All time comparisons use an application `:now` bound from an injectable `Clock`, never SQL `now()`. That lets tests jump time without waiting 24h. Lateness is bounded by tick interval plus dispatch latency, normally under 1 minute.

### 4.8 Reschedule

Under the event lock: validate the new `starts_at > now` and the event is `scheduled`. If the time is unchanged, do nothing and send no emails. Otherwise set `starts_at`, `schedule_version += 1`, and enqueue a `rescheduled` email for every confirmed and waitlisted registration (key includes the new version). Then notify.

**Reminder state.** Pending reminders for the old version are `skipped` at send time (§4.5). Reminders already sent for the old time stay sent, and they no longer count. The next scheduler tick evaluates the new `starts_at`: if the new time is already within 24h, reminders go out on that tick; otherwise they go out when the new window opens. So each person gets **one reminder per schedule version**, and the latest one always matches the real date.

### 4.9 Live updates fan-out across workers

- **Writers** call `SELECT pg_notify('event_changed', :event_id)` inside their transaction. Postgres delivers it **only on commit** and drops it on rollback.
- **Each API process** runs one `Broker`: a dedicated autocommit psycopg connection doing `LISTEN event_changed`, plus a map from `event_id` to a set of `asyncio.Queue`s, one per open SSE connection. If the listener connection drops, it reconnects with backoff and pushes a `resync` to every subscriber, because notifications sent during the gap are lost.
- **The SSE handler** (`GET /api/events/{id}/stream`) sends a full **snapshot** of counts immediately on connect. On each notification it drains its queue (coalescing bursts), re-queries the counts, and sends a snapshot only if they changed. Every 15s it sends a `: keepalive` comment. The protocol is snapshot-based, not delta-based, so lost or duplicated notifications can't corrupt client state, and a reconnect just yields a fresh snapshot.
- **nginx** uses `proxy_buffering off; proxy_read_timeout 1h;` for the stream location.
- **The worker** (which doesn't serve SSE) also calls `pg_notify` when it changes something visible, though in practice reminders don't change counts.

### 4.10 Registration state machine

```
                 seat free
  (register) ───────────────▶ confirmed ──── check-in ────▶ checked_in  (terminal)
      │                          │  ▲
      │ full                     │  │ promotion (FIFO, same tx as seat freed)
      ▼                          │  │
  waitlisted ────────────────────┼──┘
      │                          │
      │ cancel                   │ cancel (before starts_at)
      ▼                          ▼
  cancelled  (terminal; re-registering creates a NEW row with a new ticket and goes to the back of the line)
```
Disallowed transitions (each one is an explicit error): `checked_in → cancelled` (409 `already_checked_in`), `cancelled → *` (cancel again returns 200 idempotently, with no change), `waitlisted → checked_in` (409 `ticket_not_active`).

Event status: `scheduled → cancelled` (terminal). It's a column on `events`. Registrations keep their own statuses for history.

## 5. Data model

All timestamps are `timestamptz` stored in UTC. The API speaks ISO-8601 with offset, and the browser renders local time. IDs are UUIDv4 generated in the app, so URLs aren't enumerable.

### `events`
| column | type | constraints |
|---|---|---|
| id | uuid | PK |
| title | text | NOT NULL, CHECK `char_length(title) BETWEEN 1 AND 200` |
| description | text | NOT NULL DEFAULT '', CHECK length ≤ 5000 |
| starts_at | timestamptz | NOT NULL |
| capacity | integer | NOT NULL, CHECK `capacity BETWEEN 1 AND 100000` |
| seats_taken | integer | NOT NULL DEFAULT 0, CHECK `seats_taken >= 0 AND seats_taken <= capacity` |
| status | `event_status` enum(`scheduled`,`cancelled`) | NOT NULL DEFAULT `scheduled` |
| schedule_version | integer | NOT NULL DEFAULT 1 |
| created_at, updated_at | timestamptz | NOT NULL |

Index: `ix_events_starts_at_scheduled ON events (starts_at) WHERE status='scheduled'` (scheduler scan).

### `registrations`
| column | type | constraints |
|---|---|---|
| id | uuid | PK |
| event_id | uuid | NOT NULL FK → events(id) ON DELETE RESTRICT |
| email | text | NOT NULL (as entered, trimmed) |
| email_normalized | text | NOT NULL, CHECK `email_normalized = lower(email_normalized)` |
| status | `registration_status` enum(`confirmed`,`waitlisted`,`cancelled`,`checked_in`) | NOT NULL |
| ticket_code | char(8) | NOT NULL UNIQUE |
| manage_token | text | NOT NULL UNIQUE |
| queue_seq | bigint | NULL; UNIQUE; set when first waitlisted |
| created_at, updated_at | timestamptz | NOT NULL |
| confirmed_at, cancelled_at, checked_in_at | timestamptz | NULL |

Constraints and indexes:
- `uq_registrations_active_email UNIQUE (event_id, email_normalized) WHERE status <> 'cancelled'`: **one seat or waitlist entry per email per event**.
- `ck_checked_in_has_time CHECK ((status = 'checked_in') = (checked_in_at IS NOT NULL))`
- `ck_waitlisted_has_seq CHECK (status <> 'waitlisted' OR queue_seq IS NOT NULL)`
- `ix_registrations_event_status (event_id, status)` for stats and lists
- `ix_registrations_waitlist (event_id, queue_seq) WHERE status='waitlisted'` for FIFO promotion
- Sequence `registration_queue_seq`.

`manage_token` is stored in plaintext. **Known trade-off:** the outbox body already contains the link, so hashing the column alone wouldn't protect it. This is documented, not hidden.

### `email_outbox`
| column | type | constraints |
|---|---|---|
| id | bigint identity | PK |
| kind | `email_kind` enum (ticket, waitlisted, promoted, reminder, rescheduled, event_cancelled, cancelled) | NOT NULL |
| dedupe_key | text | NOT NULL **UNIQUE** |
| event_id | uuid | NOT NULL FK |
| registration_id | uuid | NULL FK |
| schedule_version | integer | NULL (reminder/rescheduled) |
| to_email, subject, body_text | text | NOT NULL |
| status | `outbox_status` enum(pending, sending, sent, failed, skipped) | NOT NULL DEFAULT pending |
| attempts | integer | NOT NULL DEFAULT 0 |
| next_attempt_at | timestamptz | NOT NULL |
| locked_until, sent_at | timestamptz | NULL |
| last_error | text | NULL |
| created_at | timestamptz | NOT NULL |

Index: `ix_outbox_due (next_attempt_at) WHERE status IN ('pending','sending')`.

## 6. Edge cases: explicit decisions

| # | Case | Decision |
|---|------|----------|
| E1 | Same email registers twice (also concurrently) | Returns the existing registration, 200 `created:false`. No second row and no second email (avoids spam amplification). The partial unique index is the guarantee. |
| E2 | Re-register after cancelling | Allowed. It creates a **new** row with a new ticket code and goes through normal seat/waitlist logic: the back of the queue if full. The old row stays `cancelled` for history. |
| E3 | Email case or whitespace variants (`A@X.com ` vs `a@x.com`) | Same person, after normalization (A10). |
| E4 | Register for a past or started event | 409 `registration_closed`. |
| E5 | Register for a cancelled event | 409 `event_cancelled`. |
| E6 | Reduce capacity below `seats_taken` | **Rejected** with 409 `capacity_below_taken` and the current count. We never bump confirmed people. The organizer must ask people to cancel first. Reducing to ≥ seats_taken is fine. |
| E7 | Increase capacity while people are waitlisted | Promote FIFO up to the new free seats in the same transaction, with `promoted` emails. |
| E8 | Cancel after check-in | 409 `already_checked_in`. Attendance is a recorded fact, and the seat was physically used. |
| E9 | Cancel twice | 200 idempotent, returns `cancelled`, no second email. |
| E10 | Cancel after event start | 409 `event_started`. Promoting someone into an event already in progress makes no sense. |
| E11 | Event cancelled by organizer | `events.status=cancelled`. `event_cancelled` email to confirmed + waitlisted. Register, cancel, check-in and reschedule are blocked (409 `event_cancelled`). Pending reminders are skipped at send time (guard checks event status too). Registration rows keep their status. |
| E12 | Promotion email fails | The seat stays. The email retries with backoff up to 8 attempts, then `failed`, visible in organizer stats. |
| E13 | Mailpit down at registration | Registration still succeeds (only the outbox row is written), and emails flush when Mailpit returns. |
| E14 | Reschedule to the past | 422 `starts_in_past`. |
| E15 | Reschedule to the same time | 200 no-op, no emails, no version bump. |
| E16 | Reschedule into the <24h window | Reminders go out on the next scheduler tick (new version). |
| E17 | Someone gets a seat while the event is already <24h away | Ticket email now, reminder on the next tick (A6). |
| E18 | Worker down across the 24h mark | Late reminder after restart if the event hasn't started, none if it has (§4.7). |
| E19 | Check-in with wrong-event code | 404 `ticket_not_found`. Codes are scoped per event on the check-in endpoint. |
| E20 | Check-in of a waitlisted or cancelled ticket | 409 `ticket_not_active` with the status. |
| E21 | Ticket code typed with lowercase, spaces, dash, O/0 confusion | Normalized before lookup. |
| E22 | Ticket code collision on generation | Unique index violation, retry up to 5 times with a new code (practically never happens). |
| E23 | SSE client disconnects or reconnects | Fresh snapshot on reconnect. The server cleans up the subscriber queue in `finally`. |
| E24 | Listener connection to Postgres drops | Reconnect with backoff, then `resync` to all subscribers. |
| E25 | Organizer in two tabs | Same cookie, both get live updates. No conflict, because every mutation is server-validated under lock. |
| E26 | Very large waitlist promotion (capacity +1000) | Single transaction. Fine at this scale. Not optimized further. |
| E27 | Event deleted | Not supported (no endpoint). Cancel instead, which keeps history and email trail. |

## 7. Out of scope (stated, not hidden)

Rate limiting and abuse protection, multi-organizer accounts and roles, i18n, ticket QR images (the typed code replaces the scanner per the brief), payment, timezone per event (we show browser-local time), GDPR data deletion, horizontal scaling beyond "N API workers + N workers on one Postgres".
