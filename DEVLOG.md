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
