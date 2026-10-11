# Event Registration Service (Task 9)

Event registration with a waitlist, emailed tickets, check-in and a live organizer dashboard. The backend is FastAPI + PostgreSQL, and the frontend is React + Vite. Email goes to Mailpit.

> **Current state: phase 1 of 10 (scaffold + infrastructure).** The stack boots and the health check works end to end. **No registration features exist yet.** The honest per-phase status is in [Status](#status) and in [DEVLOG.md](DEVLOG.md).

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

## Tests

```bash
make test         # backend (pytest, real Postgres) + frontend (vitest)
make lint         # ruff, ruff format --check, mypy --strict, eslint, tsc
make test-smoke   # boots a throwaway stack FROM SCRATCH with `make up` and probes it
make test-all     # test + test-smoke
```

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
| Frontend shell calling `/api/health` | ✅ tested (vitest) and checked manually in a browser |
| Registration, waitlist, cancel, tickets, emails, check-in, live updates, reminders, reschedule | ❌ not implemented yet (phases 2–6) |
| Organizer auth | ❌ not implemented yet (phase 2) |
| Background worker (email outbox, scheduler) | ❌ not implemented yet (phase 3) |
| E2E browser tests | ❌ phase 8 |

Known limitations so far:
- Python *transitive* dependencies aren't locked. Only direct ones are pinned. npm dependencies are fully locked.
- The Vite dev-server proxy target is fixed at `localhost:8000`.
