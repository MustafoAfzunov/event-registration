# CLAUDE.md: Event Registration Service (Task 9)

These are the project rules for every session. Read `docs/ARCHITECTURE.md`, `docs/PLAN.md` and `docs/TEST_PLAN.md` before changing code. Engineers who care about **correctness under concurrency, honest documentation, and proof** will review this project.

## Stack (decided in phase 0; see DECISIONS.md)
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async + psycopg 3, Alembic, aiosmtplib, itsdangerous. Fully async.
- **DB:** PostgreSQL 16. READ COMMITTED + explicit `SELECT … FOR UPDATE` on the event row.
- **Worker:** `python -m app.worker` runs the outbox dispatcher and reminder scheduler. There's no Celery and no Redis.
- **Live updates:** SSE + Postgres `LISTEN/NOTIFY`.
- **Email:** transactional outbox, then SMTP to Mailpit.
- **Frontend:** React 18 + Vite + TypeScript, React Router, plain fetch/EventSource, served by nginx (which proxies `/api`).
- **Tests:** pytest + pytest-asyncio + httpx (real Postgres, never SQLite or mocks for DB behaviour), Vitest, Playwright.

## Commands (available from the phase noted)
```bash
docker compose up --build                 # whole stack (P1): http://localhost:8080, Mailpit http://localhost:8025, API http://localhost:8000
make test                                  # backend + frontend tests (P1+)
make test-backend                          # docker compose run --rm backend pytest -q (P1+)
make test-frontend                         # cd frontend && npm test -- --run (P1+)
make lint                                  # ruff check, ruff format --check, mypy, eslint, tsc --noEmit (P1+)
make e2e                                   # Playwright against running stack (P8+)
make migrate                               # alembic upgrade head (P1+)
docker compose down -v                     # reset everything incl. DB volume
```
If a command here goes stale, fix this file in the same commit.

## Non-negotiable rules
1. **Never claim something is done without running the tests** and showing their real output. "Should work" doesn't count.
2. **Never skip, xfail, delete or weaken a failing test** to make the suite green. Fix the code, or stop and report. The only exception is a test that is itself wrong, which needs a DECISIONS.md entry explaining why.
3. **Log every design decision in `DECISIONS.md`** with a timestamp from `date -Iseconds`: what was decided, why, and which alternatives were rejected. Don't edit old entries. Supersede them with a new entry that references the old ID.
4. **Append to `DEVLOG.md` at the end of each phase** with a timestamp from `date -Iseconds`: what was done, test command and summary output, what's not done, and surprises.
5. **One commit per phase**, message `phase N: <summary>`, made only after the tests pass. Don't start the next phase in the same session turn unless the user asks.
6. **Docs are part of the code.** If behaviour diverges from `docs/ARCHITECTURE.md` or `docs/API.md`, update the doc in the same commit and log the decision.
7. **Honesty over polish.** Known limitations go in the README and DEVLOG. Never describe untested behaviour as working.
8. **Follow the plan.** Phase scope comes from `docs/PLAN.md`. Scope changes need a DECISIONS entry.

## Correctness conventions
- Every operation that changes seat ownership (register, cancel, capacity change, reschedule, cancel event) starts with `SELECT … FROM events WHERE id=:id FOR UPDATE` in **one transaction**. Lock order is **always the event first, then registrations**.
- Emails are **only** created by inserting into `email_outbox` inside the business transaction with a deterministic `dedupe_key` (`ON CONFLICT DO NOTHING`). Never send SMTP from a request handler.
- Every mutating transaction that changes counts calls `pg_notify('event_changed', event_id)` before commit.
- Never call SQL `now()` or `datetime.now()` in business logic. Use the injected `Clock` and pass `:now` as a bound parameter.
- Status transitions follow the state machine in ARCHITECTURE §4.10. Anything else raises a typed domain error that maps to the `code` in `docs/API.md`.
- DB constraints are the last line of defence. Don't remove or loosen one to make code work.
- Concurrency tests must use **separate DB connections or real HTTP**, never a shared session.

## Coding conventions
- **Python:** type hints everywhere. `ruff` (line length 100) and `mypy --strict` on `app/`. Business logic lives in `app/services/*` (pure functions taking a session and a clock). `app/api/*` stays thin: parse, call the service, map errors. Pydantic schemas live in `app/schemas.py`. No bare `except`.
- **Errors:** raise `DomainError(code, message, http_status, details)`, which a single exception handler turns into the API error envelope.
- **Migrations:** one Alembic revision per schema change, reviewed by hand. Constraints and partial indexes are written explicitly. Never edit a migration that's already committed.
- **TypeScript:** `strict: true`. A single `api.ts` client returns typed results, and `errors.ts` maps API `code` to messages. Components stay small. No global state library.
- **Tests:** names describe behaviour (`test_<what>_<expected>`). Name new tests in `docs/TEST_PLAN.md` when they cover a requirement.
- **Secrets:** read only from env. `.env.example` holds dev-only values. Never log tokens, ticket codes or passwords.
- **Commits:** end the message with the attribution line given by the environment.
