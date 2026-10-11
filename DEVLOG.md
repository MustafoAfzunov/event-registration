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

---

## 2026-10-11T14:50:17+06:00 · Phase 2: Registration core, waitlist and locking

**Context:** the user approved the phase 2 plan as part of the phase 3 request (D-031). Phase 2 is committed on its own, before phase 3.

**Done**
- **API:**
  - Organizer: login/logout/me (signed httpOnly SameSite=Strict cookie), events create/list/patch. No delete, by design.
  - Public: events list/get, register.
  - Participant: `GET /api/registrations/{token}`, `POST …/cancel`.
  - One error envelope for all errors (`DomainError`, validation, 404/405).
- **Concurrency core** (`app/services/seats.py`): `lock_event` (`SELECT … FOR UPDATE`) starts every seat-changing transaction, with lock order event → registrations. `seats_taken` is changed only under the lock. FIFO promotion runs in the same transaction that frees the seat (cancel, capacity increase).
- **Registration:**
  - Email trimmed, validated (ASCII, no DNS) and lowercased.
  - A duplicate returns the existing row (200, no email).
  - Waitlist via `queue_seq` taken under the lock.
  - Ticket-code collisions retried in a SAVEPOINT.
  - The unique-index backstop is handled.
- Outbox rows (ticket / waitlisted / promoted / cancelled) are written in the same transaction, with dedupe keys. **Not sent yet.**
- **Test tooling:** `tests/concurrency.py` (lock gate proven via pg_locks), `tests/invariants.py` (checked after every concurrency test), helpers, `make test-concurrency-loop N=20`.
- **Smoke:** a new 8th probe runs organizer login → create event → register ×2 (confirmed, waitlisted) through nginx on the real 2-worker stack.

**Tests:** `make lint && make test-all` → lint/types clean, **backend 98 passed**, frontend 4 passed, smoke 8/8.

**Concurrency evidence**
- `make test-concurrency-loop N=20`: **20/20 runs passed** (6 tests each, ~4s per run). Since the last-seat test does 25 gated rounds, that's **500 proven last-seat races**.
- Your 6 scenarios:
  1. 20 parallel / 5 seats → 5 + 15, positions 1..15.
  2. Last seat, gated.
  3. Same email ×10, identical and case/whitespace variants → 1 row, 1 outbox row.
  4. Case/whitespace variants.
  5. FIFO promotion, including skipping a waitlister who left.
  6. 5 cancels + 10 registrations in parallel, random order: an observer saw confirmed ≤ 5 throughout, the 5 oldest waitlisters got the seats, and no newcomer jumped the queue.
- **Mutation** (`FOR UPDATE` removed): 3/6 concurrency tests failed, every time with `CheckViolation ck_events_seats_taken_range`. The DB refused to overbook (D-040). Restored.

**Surprises**
- The first gated run reported "1/20 waiting" while all 20 were blocked. `pg_stat_activity` is snapshotted per transaction, so the poller now runs in AUTOCOMMIT (D-033).
- The deployed-stack smoke probe got 422 for `@smoke.test`. email-validator rejects special-use domains, which is correct, so it's now pinned in tests (D-042).
- SQLAlchemy 2.1 types `Select` variadically (`Select[Event]`). mypy caught it.

**Not done / known gaps**
- Emails aren't sent (phase 3). No check-in, live updates, reminders, reschedule or event cancel endpoints (phases 4–6). No UI (phase 7).
- E5/E8 edge cases (cancelled event, checked-in ticket) are tested by setting state via SQL until those endpoints exist.
- Concurrency tests are in-process (one Python process, many Postgres connections). The multi-process HTTP stress test is phase 8.
- No rate limiting. Duplicate registration reveals registration status (D-036).

**Next:** phase 3 (email worker), in this same session, per the user's instruction.
