# CLAUDE.md: Event Registration Service (Task 9)

These are the project rules for every session. Read `docs/ARCHITECTURE.md`, `docs/PLAN.md` and `docs/TEST_PLAN.md` before changing code. Engineers who care about **correctness under concurrency, honest documentation, and proof** will review this project.

## Stack (decided in phase 0; see DECISIONS.md)
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async + psycopg 3, Alembic, aiosmtplib, itsdangerous. Fully async.
- **DB:** PostgreSQL 16. READ COMMITTED + explicit `SELECT … FOR UPDATE` on the event row.
- **Worker:** `python -m app.worker` (compose service `worker`) runs the outbox dispatcher (phase 3) and, from phase 6, the reminder scheduler. There's no Celery and no Redis. Email delivery is **at-least-once** by user decision (D-043). Never describe it as exactly-once delivery.
- **Live updates:** SSE + Postgres `LISTEN/NOTIFY`.
- **Email:** transactional outbox, then SMTP to Mailpit.
- **Frontend:** React 19 + Vite 8 + TypeScript 6.0, React Router, plain fetch/EventSource, served by nginx (which proxies `/api`).
- **Tests:** pytest + pytest-asyncio + httpx (real Postgres, never SQLite or mocks for DB behaviour), Vitest, Playwright.

## Commands (available from the phase noted)
```bash
make up                                    # build + start whole stack, waits for healthy: app :8080, API :8000, Mailpit :8025, db :5433
make down / make clean                     # stop / stop AND delete DB volume
make test                                  # backend (pytest, real Postgres eventreg_test) + frontend (vitest), all in containers
make test-backend                          # pytest -v in the backend-test container (extra args: docker compose --profile test run --rm backend-test pytest -k ...)
make test-frontend                         # vitest in the frontend-test container
make test-smoke                            # boots an isolated throwaway stack from scratch via `make up` and probes it
make test-concurrency-loop N=20            # tests/test_concurrency.py N times as separate pytest processes (flakiness check)
make test-all                              # test + test-smoke  <- the "full test suite" for phase reports
make lint                                  # ruff check, ruff format --check, mypy --strict, eslint, tsc --noEmit
make migrate                               # alembic upgrade head
make e2e                                   # Playwright (2 browser contexts) against an isolated stack; JUnit -> reports/e2e.xml
make stress                                # scripts/stress.py against the running dev stack
make proof                                 # everything + requirement table from docs/TEST_PLAN.md  <- the "full test suite" from phase 8 on
```
If a command here goes stale, fix this file in the same commit.

## Non-negotiable rules
1. **Never claim something is done without running the tests** and showing their real output. "Should work" doesn't count.
2. **Never skip, xfail, delete or weaken a failing test** to make the suite green. Fix the code, or stop and report. The only exception is a test that is itself wrong, which needs a DECISIONS.md entry explaining why.
3. **Log every design decision in `DECISIONS.md`** with a timestamp from `date -Iseconds`: what was decided, why, and which alternatives were rejected. Don't edit old entries. Supersede them with a new entry that references the old ID.
4. **Append to `DEVLOG.md` at the end of each phase** with a timestamp from `date -Iseconds`: what was done, test command and summary output, what's not done, and surprises.
5. **One commit per phase**, message `phase N: <summary>`, made only after the tests pass. Don't start the next phase in the same session turn unless the user asks.
6. **Docs are part of the code.** If behaviour diverges from `docs/ARCHITECTURE.md` or `docs/API.md`, update the doc in the same commit and log the decision. `docs/TEST_PLAN.md` is machine-checked: `scripts/proof_report.py` resolves every `file::test` reference against the JUnit results, so a renamed or removed test makes `make proof` fail with MISSING. Update the plan in the same commit.
7. **Honesty over polish.** Known limitations go in the README and DEVLOG. Never describe untested behaviour as working.
8. **Follow the plan.** Phase scope comes from `docs/PLAN.md`. Scope changes need a DECISIONS entry.

## Correctness conventions
- Every operation that changes seat ownership (register, cancel, capacity change, reschedule, cancel event) starts with `SELECT … FROM events WHERE id=:id FOR UPDATE` in **one transaction**. Lock order is **always the event first, then registrations**.
- Tests that check emails read them from the **test** Mailpit (`tests/mailpit.py`, service `mailpit-test`) and drive the worker logic via the `make_dispatcher` fixture (shared FixedClock). Fault injection lives in `tests/senders.py`.
- Emails are **only** created by inserting into `email_outbox` inside the business transaction with a deterministic `dedupe_key` (`ON CONFLICT DO NOTHING`). Never send SMTP from a request handler.
- Every mutating transaction that changes counts calls `pg_notify('event_changed', event_id)` before commit.
- Never call SQL `now()` or `datetime.now()` in business logic. Use the injected `Clock` and pass `:now` as a bound parameter.
- Status transitions follow the state machine in ARCHITECTURE §4.10. Anything else raises a typed domain error that maps to the `code` in `docs/API.md`.
- DB constraints are the last line of defence. Don't remove or loosen one to make code work.
- Concurrency tests must use **separate DB connections or real HTTP**, never a shared session. To claim "at the same moment", use `tests/concurrency.py` (`event_lock_gate` + `wait_for_lock_waiters`), which proves via `pg_locks` that all N requests were blocked on the lock before releasing them. Finish every concurrency test with `tests/invariants.py::assert_invariants`.
- Any write that changes what a stream shows must call `notify_event_changed(session, event_id)` inside its transaction (`app/live/broker.py`). SSE tests must use real uvicorn processes (`live_servers` fixture), because httpx's ASGI transport buffers whole responses.
- Services own their transactions (`async with sessionmaker() as s, s.begin()`). Routes never open sessions for writes.

## Coding conventions
- **Schema changes:** update `app/models.py` AND add a migration. `test_models_match_migrations` fails on any drift.
- **Python:** type hints everywhere. `ruff` (line length 100) and `mypy --strict` on `app/`. Business logic lives in `app/services/*` (pure functions taking a session and a clock). `app/api/*` stays thin: parse, call the service, map errors. Pydantic schemas live in `app/schemas.py`. No bare `except`.
- **Errors:** raise `DomainError(code, message, http_status, details)`, which a single exception handler turns into the API error envelope.
- **Tooling runs in containers.** Don't depend on host Python/Node versions. Regenerate `frontend/package-lock.json` inside `node:22-alpine` (host npm 10.8 crashes on it).
- **Migrations:** one Alembic revision per schema change, reviewed by hand. Constraints and partial indexes are written explicitly. Never edit a migration that's already committed.
- **TypeScript:** `strict: true`. A single `api.ts` client returns typed results, and `errors.ts` maps API `code` to messages. Components stay small. No global state library.
- **Tests:** names describe behaviour (`test_<what>_<expected>`). Name new tests in `docs/TEST_PLAN.md` when they cover a requirement.
- **Secrets:** read only from env. `.env.example` holds dev-only values. Never log tokens, ticket codes or passwords.
- **Commits:** end the message with the attribution line given by the environment.
