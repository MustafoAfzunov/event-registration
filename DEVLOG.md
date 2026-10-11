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
