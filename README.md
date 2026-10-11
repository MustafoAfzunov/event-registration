# Event Registration Service (Task 9)

Event registration with a waitlist, emailed tickets, check-in and a live organizer dashboard. The backend is FastAPI + PostgreSQL, and the frontend is React + Vite. Email goes to Mailpit.

> **Current state: phase 8 of 10.** The registration core works via the API (events, register, cancel, waitlist, FIFO promotion, concurrency-safe seats). A background worker emails tickets, waitlist notices and promotions to Mailpit. Organizers can check tickets in (exactly once) and read stats. Counters update live over SSE across backend workers. A scheduler in the worker sends exactly one reminder per confirmed participant 24h before the event, and rescheduling notifies everyone. A React UI covers every flow (public event page, ticket page, organizer dashboard, check-in). The honest per-phase status is in [Status](#status) and in [DEVLOG.md](DEVLOG.md).

## Quick start

Requirements: Docker with the Compose v2 plugin, and `make`. Nothing else is needed on the host: tests and linters run in containers too.

```bash
make up
```

This copies `.env.example` to `.env` if it's missing, builds the images, applies database migrations, and returns once every service is healthy. Then open:

| What | URL |
|---|---|
| App (React, served by nginx) | http://localhost:8080 |
| API health | http://localhost:8000/api/health (also `/health`) |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Mailpit (captured emails) | http://localhost:8025 |
| Postgres (for psql/GUI) | `localhost:5433`, user/password/db `eventreg` |

The app page shows **"Backend: ok · Database: ok"** when the browser → nginx → backend → Postgres path works.

If a port clashes with something on your machine, change it in `.env`.

```bash
make down      # stop (keeps data)
make clean     # stop and DELETE the database volume
make logs      # follow logs
make help      # all targets
```

Without make, `docker compose up --build` also works (the compose file has defaults for every variable).

## Using the app

1. Open http://localhost:8080/admin and log in with `ORGANIZER_PASSWORD` from `.env` (dev default: `organizer-dev-password`).
2. Create an event. Its dashboard shows live counters and the participant list.
3. Open the event's **public page** (link on the dashboard) in another tab and register with any email. Use `example.com`-style addresses; special-use domains like `.test` are rejected.
4. Open http://localhost:8025 (Mailpit) to see the ticket email. Its link opens the **ticket page**, which shows the code and has a cancel button.
5. On the dashboard, open the **check-in screen** and type the code. The dashboard in the other tab updates without reloading.

## Tests

```bash
make test         # backend (pytest, real Postgres) + frontend (vitest)
make lint         # ruff, ruff format --check, mypy --strict, eslint, tsc
make test-smoke   # boots a throwaway stack FROM SCRATCH with `make up` and probes it
make test-all     # test + test-smoke
make test-concurrency-loop N=20   # concurrency tests 20x as separate processes (flakiness check)
make e2e          # Playwright, two browser contexts, against an isolated throwaway stack (~2 min)
make stress       # 250 concurrent registrations + mixed cancels against the RUNNING dev stack
make proof        # EVERYTHING above, then a PASS/FAIL table per requirement of docs/TEST_PLAN.md (~10 min)
```

`make proof` ends with a table like this (generated from the JUnit results, not written by hand):

```
Behaviour requirements
  ID     RESULT   detail
  B5     PASS     8 checks          <- last-seat race: gated pytest x25, UI race x3, stress, concurrency loop
  B7b    PASS     6 checks          <- live arrived counter: real uvicorn workers, two browser tabs
  ...
Requirements: 1 MANUAL, 43 PASS
PROOF PASS
```

A row whose referenced test doesn't exist shows **MISSING** and fails the proof, so the plan can't claim tests that aren't there. P7 ("honest README") is the only row that can't be automated.

- **Backend tests** run against a real PostgreSQL database (`eventreg_test`, created automatically on first DB start), never SQLite or mocks. The suite refuses to run against any database whose name doesn't end in `_test`.
- **The smoke test** (`scripts/smoke_compose.sh`) uses its own compose project, volumes and ports (18080/18000/18025/15433), so it never touches your dev stack or data. It removes everything afterwards. Set `SMOKE_NO_CACHE=1` to also rebuild images without Docker's build cache.

## Architecture (short)

```
browser ──▶ frontend (nginx: static React build, proxies /api) ──▶ backend (FastAPI, 2 uvicorn workers) ──▶ PostgreSQL
                                                                     migrate (one-shot alembic upgrade head) ──▶ PostgreSQL
mailpit (SMTP :1025, UI :8025): wired up now, used from phase 3
```

Full design, including the concurrency mechanisms, data model and edge-case decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). API contract: [docs/API.md](docs/API.md). Plan: [docs/PLAN.md](docs/PLAN.md). Requirement→test map: [docs/TEST_PLAN.md](docs/TEST_PLAN.md). Every decision with its reasoning: [DECISIONS.md](DECISIONS.md).

## Status

| Area | State |
|---|---|
| Compose stack (db, mailpit, migrate, backend, frontend), one command | ✅ works, proven by `make test-smoke` |
| `GET /api/health` + `/health` with DB check (200 / 503 within a 2s budget) | ✅ tested |
| Full DB schema (events, registrations, email_outbox) with constraints | ✅ migration up/down/up tested; key constraints tested directly |
| UI: event list, event page (live seats, register, outcomes), ticket page (code, cancel), organizer login / events / dashboard (live counters, participants, edit, reschedule, cancel event), check-in screen | ✅ 38 component tests (mocked API) + manual two-tab walkthrough on the real stack; automated browser E2E is phase 8 |
| Organizer login (cookie) + event create / list / update (capacity changes promote the waitlist) | ✅ API, tested |
| Register by email (normalized, duplicate-safe), waitlist, cancel via manage link, FIFO promotion | ✅ API, tested |
| Last-seat race / parallel registrations / same email in parallel / parallel cancel + register | ✅ real-Postgres concurrency tests, passed 20 runs in a row (`make test-concurrency-loop`) |
| Emails: ticket, waitlist notice, promotion with ticket, cancellation confirmation | ✅ outbox row written in the same transaction; `worker` sends via SMTP to Mailpit with retry and backoff. Tested in Mailpit, including worker restarts. |
| Check-in by ticket code (organizer login): exactly once, also under concurrent scans; clear errors (`ticket_not_found`, `already_checked_in`, `ticket_cancelled`, `ticket_waitlisted`, `invalid_code_format`) | ✅ API, tested incl. gated races |
| Organizer stats (confirmed, checked in, registered, waitlisted, cancelled, free seats, email delivery counts) + registrations list | ✅ API, tested after every transition and under concurrent writes |
| Live updates over SSE: public seats-left stream, organizer stats stream; works across uvicorn workers and processes (Postgres LISTEN/NOTIFY); snapshot on (re)connect | ✅ tested against real uvicorn processes (incl. `--workers 2`) and through nginx in the smoke test |
| Reminder 24h before (exactly one per confirmed person per event date), reschedule (emails everyone, reminder follows the new date), event cancel | ✅ tested with a controllable clock, 3 concurrent scheduler instances, 3 real worker processes, crash/restart cases; smoke on the real stack |
| Background worker: email outbox | ✅ (`worker` service). Reminder scheduler ❌ phase 6 |
| E2E in real browsers (two contexts): live seat counter, last-seat race through the UI, cancel → promotion email, check-in once + live organizer counter, reschedule emails, reminder | ✅ `make e2e` (9 tests, isolated stack, real Mailpit) |
| Stress over HTTP through nginx (2 workers): 250 concurrent registrations, then concurrent cancels + registrations | ✅ `make stress`: 17 invariants hold. Throughput for **one** event is about 120 registrations/s, with p95 about 2s at 250 simultaneous requests, because every registration for an event is serialized by its row lock. Different events don't block each other. |

### Email delivery guarantee (read this)

- **Each email is queued exactly once.** The email row is written in the same database transaction as the seat change, under a unique key, so a repeat registration or a retried request can't queue it twice.
- **Delivery is at-least-once.** The worker marks an email sent only after the SMTP server accepted it.
  - On a graceful restart (SIGTERM, `docker compose restart worker`), on a crash before sending, or with several workers running at once, **no duplicates** occur. All of these are tested.
  - The one case that can produce a duplicate: the worker dies in the instant after Mailpit accepted a message but before the database recorded it. That single message is sent again, with the same Message-ID. This is tested and bounded to ≤1 message per crash.
  - The alternative (mark first, then send) would instead silently lose a ticket. We chose duplicate over loss.
- If Mailpit is down, registrations still succeed and emails are retried with exponential backoff (5s, 10s, 20s … capped at 1h; `failed` after 8 attempts).

To see emails: open http://localhost:8025 after registering. Tests use a separate `mailpit-test` container, so running tests never empties your dev inbox.

Try live updates in a terminal: `curl -N localhost:8080/api/events/<event-id>/stream`, then register from another terminal.

### Reminder policy (read this)

- Reminders become due **24h before** the start and go to people who are **confirmed** at that moment. Waitlisted and cancelled people don't get one, and neither do people already checked in.
- If someone gets a seat (registers, is promoted, or the event is created/rescheduled) when the event is already less than 24h away, they get their reminder at the next scheduler tick (default every 30s).
- **Worker downtime:** missed reminders are sent late after the restart if the event hasn't started yet, and **never** after the start.
- **Reschedule:**
  - Everyone confirmed, waitlisted or checked in gets a "New date" email.
  - Unsent reminders for the old date are dropped.
  - Exactly one reminder follows for the new date, so a person can receive one reminder per date.
- Someone who cancels and re-registers doesn't get a second reminder for the same date.

Known limitations so far:
- No rate limiting on login or registration. A duplicate registration reveals whether an email is already registered for that event (accepted trade-off, D-036).
- Python *transitive* dependencies aren't locked. Only direct ones are pinned. npm dependencies are fully locked.
- The Vite dev-server proxy target is fixed at `localhost:8000`.
