# Event Registration Service (Task 9)

People register for an event by email and get an emailed ticket with a code. When the event is full they join a waitlist, and when someone cancels, the first person waiting gets the seat and an email automatically. Organizers manage events, see live counters (registered, waitlisted, checked in), check tickets in at the door by typing the code, and can reschedule (everyone is emailed). Every confirmed participant gets exactly one reminder 24 hours before the event.

**Stack:** FastAPI (Python 3.12) + PostgreSQL 16 backend, a separate email/scheduler worker, a React 19 + Vite + Tailwind CSS 3 frontend (the "Kinetic Horizon" design from `docs/stitch_event_registration_app_screens/`) served by nginx, and Mailpit as the email inbox. Everything runs with one `docker compose` command.

**Where to look next:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (design and concurrency mechanisms), [docs/API.md](docs/API.md) (API contract), [docs/TEST_PLAN.md](docs/TEST_PLAN.md) (requirement → test map), [docs/REVIEW.md](docs/REVIEW.md) (independent review and open findings), [DECISIONS.md](DECISIONS.md) (every decision with timestamp and reason), [DEVLOG.md](DEVLOG.md) and [docs/TIMELINE.md](docs/TIMELINE.md) (how it was built).

## Quick start

**Prerequisites**
- Docker with the Compose v2 plugin. Verified with Docker 29.1.3 and Compose v2.27.0 on Linux.
- `make`.
- Free host ports 8080, 8000, 8025, 1025 and 5433 (all configurable in `.env`).
- For `make test-smoke`, `make e2e` and `make proof` only: `bash`, `curl` and GNU `date`. Linux works as is; on macOS install coreutils ([REVIEW M5](docs/REVIEW.md)).
- Internet access on the first run, to pull images and dependencies.

**Run**

```bash
make up
```

This copies `.env.example` to `.env` if there is none, builds the images, applies database migrations, and returns once every service is healthy. A re-run with a warm Docker cache took 24s in the final check. The very first build downloads images and dependencies and takes several minutes. Without make, `docker compose up --build` works too: the compose file has a default for every variable, and the `-d --wait` variant was checked from a clean clone without a `.env`.

| What | URL |
|---|---|
| App | http://localhost:8080 |
| Organizer login | http://localhost:8080/admin. Password: `ORGANIZER_PASSWORD` in `.env` (dev default `organizer-dev-password`) |
| Emails (Mailpit) | http://localhost:8025 |
| API health / OpenAPI docs | http://localhost:8000/api/health · http://localhost:8000/docs |
| Postgres | `localhost:5433`, user, password and db `eventreg` |

```bash
make down    # stop (keeps data)
make clean   # stop and DELETE the database volume
make help    # every target
```

**Try it** (about 2 minutes)
1. Log in at `/admin` and create an event with 1 seat. Its dashboard shows live counters.
2. Open the event's public page (link on the dashboard) in a second tab and register two emails (use `example.com`-style addresses; special-use domains like `.test` are rejected). The first gets the seat, the second is waitlisted. The dashboard updates without reloading.
3. In Mailpit, open the first person's ticket email and follow its link to the ticket page. Cancel: the waitlisted person is promoted and gets an email with their ticket.
4. On the dashboard, open **Check-In Terminal** (top navigation) and type the promoted person's ticket code. You get a green "Welcome!" the first time and a red "Already used" the second, and the dashboard counter changes live.

For live updates from a terminal: `curl -N localhost:8080/api/events/<event-id>/stream`, then register from another terminal.

## Architecture (short)

```
browser tabs ──HTTP+SSE──> frontend (nginx: React build, proxies /api) ──> backend (FastAPI, uvicorn --workers 2) ──┐
                                                                                                                 ├──> PostgreSQL
Mailpit <──SMTP── worker (email outbox dispatcher + reminder scheduler) ─────────────────────────────────────────────┘
migrate (one-shot: alembic upgrade head) runs before backend and worker start
```

- **No overbooking, no double seat.** Every operation that changes who holds a seat (register, cancel, capacity change, reschedule, cancel event) runs in one transaction that first locks the event row (`SELECT … FOR UPDATE`). Postgres also enforces it on its own: `CHECK (seats_taken <= capacity)` and a partial unique index allowing one active registration per (event, normalized email).
- **Waitlist is FIFO.** Waiting order comes from a sequence assigned under the lock. A freed seat goes to the first person waiting in the *same* transaction, so a newcomer can never take it first.
- **Emails use a transactional outbox.** The email row is written in the same transaction as the state change, with a unique dedupe key, so it's queued exactly once. The worker sends it to Mailpit with leases, fencing, retries and backoff. Delivery is **at-least-once**: one narrow crash window can produce a duplicate with the same Message-ID, and it never loses one ([D-043](DECISIONS.md)).
- **Reminders don't depend on in-memory timers.** The scheduler is driven entirely by the database: it locks due events with `FOR UPDATE SKIP LOCKED`, and the outbox dedupe key is the "reminder exists" record. It's restart-safe and safe with several instances. Each reminder is re-checked when sent (still confirmed? same date? not started?).
- **Live updates use SSE** with Postgres `LISTEN/NOTIFY`, so they work across both uvicorn workers. Each stream sends a full snapshot on connect and resyncs after a lost connection.
- **Check-in** is a single conditional `UPDATE … WHERE status='confirmed'`, so a ticket can be used exactly once even with parallel scans.
- **Auth:**
  - **Organizer:** one shared password, then a signed httpOnly `SameSite=Strict` cookie.
  - **Participants:** a secret link in their emails (`/r/<token>`) to view or cancel. The ticket code and link are delivered only by email, never in an API response.

## What works (with the evidence)

| Requirement (brief) | How it is proven |
|---|---|
| Separate backend + frontend over the network, Postgres, one-command run, Mailpit | `make test-smoke`: a throwaway stack from scratch via `make up`, 13 probes through nginx to the 2-worker backend |
| Register by email, cancel, waitlist, ticket with code | backend tests + browser E2E (Playwright) reading the real emails from Mailpit |
| Registration email with ticket | `test_email_delivery.py`, E2E `register_receive_ticket_email_and_view_ticket` |
| Repeat registration never creates a second seat | DB unique index test, 10 identical requests in parallel give 1 row, E2E in two tabs, stress with duplicate variants |
| Full → waitlist; cancel → first in line gets the seat and an email | FIFO tests, E2E with a real cancel dialog and the promotion email from Mailpit, stress (20 parallel cancels: 20/20 promoted in queue order) |
| Two people for the last seat → one seat, one waitlist | gated pytest (both requests proven waiting on the lock, 25 rounds), concurrency loop, UI race in two browser contexts, stress |
| Exactly one reminder 24h before | simulated-clock tests, 3 concurrent scheduler instances, 3 real worker processes, crash between claim and send, E2E with an event 23h ahead |
| Check-in only once; organizer counter live | gated parallel check-in (1 success, 9 rejected), E2E door tab → dashboard tab without reload, SSE across separate uvicorn processes |
| Reschedule emails every participant | Mailpit-verified tests (confirmed, waitlisted, checked-in; not cancelled), the reminder follows the new date, E2E through the dashboard |
| Works with two browser tabs | Playwright with two browser contexts; no-reload is asserted, not assumed |

## Proof: `make proof`

```bash
make proof
```

It runs **everything**, keeps going after a failure, and ends with a requirement-by-requirement table computed from the JUnit results (`scripts/proof_report.py`). No part of the table is written by hand:

| Step | What runs |
|---|---|
| lint | ruff, ruff format, mypy --strict, eslint, tsc |
| backend | pytest against a real Postgres test DB and a test Mailpit, including real uvicorn and worker processes |
| frontend | Vitest component tests (real routes, mocked API, fake EventSource) |
| concurrency_loop | the concurrency tests 5 times as separate processes (`PROOF_LOOP=N` to change) |
| smoke | `make up` from scratch in an isolated project, 13 probes |
| e2e | Playwright (Chromium), two browser contexts, against an isolated stack with real Mailpit |
| stress | `scripts/stress.py`: 250 concurrent registrations (incl. duplicate variants) on 50 seats, then 20 cancels + 30 registrations at once; 17 invariants |

Each TEST_PLAN row gets PASS, FAIL, MISSING (it names a test that doesn't exist or didn't run) or MANUAL. Any FAIL or MISSING fails the proof.

**Latest run** (phase 7b, in the working copy: all seven steps of `make proof` passed, then the requirement table was regenerated; the first table run flagged one wrong test reference of mine as MISSING, which was fixed. The earlier phase 10 run from a clean `git clone` is recorded in [DEVLOG](DEVLOG.md); 245 test cases then, 293 now after the new UI tests):

```

Pipeline steps
  lint               PASS
  backend            PASS
  frontend           PASS
  concurrency_loop   PASS
  smoke              PASS
  e2e                PASS
  stress             PASS
  test cases         293 passed, 0 failed, 0 skipped (backend+frontend+e2e)

Platform requirements
  ID                                 RESULT   detail
  P1                                 PASS     3 checks
  P2                                 PASS     2 checks
  P3                                 PASS     1 checks
  P4                                 PASS     2 checks
  P5                                 PASS     4 checks
  P6                                 PASS     7 checks
  P7                                 MANUAL   

Domain requirements
  ID                                 RESULT   detail
  D1                                 PASS     3 checks
  D2                                 PASS     4 checks
  D3                                 PASS     5 checks
  D4                                 PASS     5 checks
  D5                                 PASS     5 checks
  D6                                 PASS     5 checks
  D7                                 PASS     5 checks

Behaviour requirements
  ID                                 RESULT   detail
  B1                                 PASS     3 checks
  B2                                 PASS     6 checks
  B3                                 PASS     3 checks
  B4                                 PASS     6 checks
  B5                                 PASS     7 checks
  B6                                 PASS     15 checks
  B7a                                PASS     4 checks
  B7b                                PASS     6 checks
  B8                                 PASS     7 checks

Edge cases (ARCHITECTURE §6) → tests
  ID                                 RESULT   detail
  (19 edge-case rows E1–E24, all PASS: omitted here, shown in full by make proof)
  Email: exactly-once enqueue, at... PASS     8 checks
  Review H1: one unsendable email... PASS     3 checks
  Review H2: manage tokens never ... PASS     2 checks
  UI design (phase 7b): Stitch de... PASS     11 checks
  Security                           PASS     3 checks

Requirements: 1 MANUAL, 46 PASS
PROOF PASS
```

Other entry points: `make test` (backend + frontend), `make lint`, `make test-smoke`, `make e2e`, `make stress` (against the running dev stack), `make test-concurrency-loop N=20`.

## What doesn't work, or wasn't done, and why

**Open review findings** ([docs/REVIEW.md](docs/REVIEW.md) has evidence and a ready reproducing test for each). Both HIGH findings were fixed test-first. Still open:
- **M1, same-site CSRF:** organizer POSTs without a body (cancel event, logout) also accept a plain HTML form submit from the same *site* (for example another port on `localhost`). `SameSite=Strict` only blocks other sites.
- **M2, logout doesn't revoke:** the organizer cookie is a stateless signed token, valid for 12h even after logout.
- **M3, dev defaults:** compose falls back to the public dev secret and password, and `COOKIE_SECURE` is off. Nothing stops `APP_ENV=production` from using them. **Set real values in `.env` for anything but local use.**
- **M4, timezones:** local-time code paths are only tested in UTC. **L1:** emails show times in UTC, while the UI shows browser-local time.
- **M5, scripts:** they need GNU `date`, so macOS needs coreutils.
- **L2–L7:**
  - L2: ticket and promotion emails aren't re-checked at send time;
  - L3: SSE disconnect cleanup is only unit-tested, and there's no cap on connections;
  - L4: three tests depend on timing;
  - L5: the seat counter matching the actual number of holders is enforced by code and tests, not by the DB;
  - L6: running without make was checked by hand but has no automated test;
  - L7: each open stream re-queries on every change.

**Limits that are part of the design:**
- **Exactly-once email *delivery* over SMTP isn't possible.** We guarantee exactly-once queueing and at-least-once delivery ([D-043](DECISIONS.md)).
- **One event's seat changes are serialized by its row lock.** Measured: 106–118 registrations/s for a single event on four earlier stress runs (p95 2.1–2.2s with 250 requests in flight), but only 48/s (p95 5.0s) on the phase 7b run, which shared the machine with other containers; the cause wasn't investigated, so treat throughput as machine-dependent. All 17 invariants held in every run. Different events don't block each other.
- **The UI last-seat race** is two near-simultaneous clicks. Proven simultaneity is in the gated backend tests.
- **The "24h before" timing** is tested with a simulated clock and an event 23h ahead, not by waiting a day.

**Out of scope (decided, not forgotten):**
- rate limiting;
- multiple organizer accounts or a door-staff role (one shared password, [A1](docs/ARCHITECTURE.md));
- per-event time zones;
- HTML emails;
- real SMTP providers (TLS/auth);
- deleting events (cancel instead);
- `Last-Event-ID` replay (a reconnect gets a fresh snapshot);
- Firefox/WebKit/mobile E2E;
- a CI pipeline (`make proof` is the local equivalent);
- a lockfile for *transitive* Python dependencies (direct ones are pinned; npm is fully locked).

## AI tools used

The project was built with **Claude Code** (Anthropic's agentic coding tool, used in the Claude desktop app) running the **Claude Opus 5.5** model (`claude-opus-5-5`). It wrote the code, tests and docs and ran the builds, tests and probes recorded in [DEVLOG.md](DEVLOG.md), one phase per prompt from the developer. It suited this task because the assignment rewards proof over assertion: an agent that can run the whole stack (real Postgres, real browsers, real email) can be required to show evidence for each step, such as failing tests first, mutation checks and a clean-clone proof run.

The developer set the phase plan and requirements, and answered the decisions the AI asked about: approving the phase 2 plan, and choosing at-least-once email delivery ([D-031](DECISIONS.md), [D-043](DECISIONS.md)).

## Templates and generated files

- **No project generator** (create-vite, cookiecutter, FastAPI templates) was used. Application code, tests, configs and docs were written in this repository by the AI tool described above.
- **`backend/alembic/script.py.mako`** follows Alembic's standard revision template. The migration itself (`0001_initial.py`) was hand-written, not autogenerated ([D-002](DECISIONS.md)).
- **Generated by tools:** `frontend/package-lock.json` and `e2e/package-lock.json` (npm), and `docs/TIMELINE.md` (by `scripts/timeline.sh` from `git log` and `DEVLOG.md`). The proof table is generated at run time by `scripts/proof_report.py`.
- **Official base images, used unmodified:** `python:3.12-slim`, `node:22-alpine`, `nginx:1.30-alpine`, `postgres:16-alpine`, `axllent/mailpit:v1.31`, `mcr.microsoft.com/playwright:v1.64.0-noble`.

## Next steps

1. Fix the open MEDIUM findings with their prepared tests:
   - CSRF guard (JSON content type or a custom header on every mutating admin call);
   - server-side session revocation;
   - refuse dev secrets when `APP_ENV=production`;
   - run the time tests in a non-UTC zone.
2. Re-validate ticket and promotion emails at send time (L2). Cap and observe SSE connections (L3).
3. CI: run `make proof` on every push. Add Firefox/WebKit to the E2E matrix.
4. Product: rate limiting on login and registration, a door-staff role, per-event time zone and localized email times.

## Design

The UI is a copy of the Stitch export in `docs/stitch_event_registration_app_screens/` (screens plus `kinetic_horizon/DESIGN.md`): the exported Tailwind theme is used unchanged (`frontend/tailwind.config.js`), so the exported classes work as is. Only what our backend supports was kept: elements such as speakers, schedule, FAQ, prices and tiers, revenue, map, QR/barcode, camera feed, wallets, search, notifications and avatars were removed, and all content comes from the API and live updates. Fonts and icons are self-hosted, so the app makes no runtime calls to Google or a CDN. Deliberate deviations from the export: a compact scrolling nav row on phones (the export hides its nav below `lg` with no replacement), and scrollbars are not hidden (the export hides them globally).

## Repository map

```
backend/   FastAPI app (app/), Alembic migration, pytest suite (tests/)
frontend/  React + Vite app, Vitest tests, nginx config
e2e/       Playwright tests (two browser contexts)
scripts/   smoke_compose.sh, e2e.sh, stress.py, proof.sh, proof_report.py, timeline.sh
docs/      ARCHITECTURE, API, PLAN, TEST_PLAN, REVIEW, TIMELINE
infra/     Postgres init script (creates the test database)
```
