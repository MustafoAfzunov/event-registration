# Prompts

Every message the developer typed in the Claude Code session, verbatim and in order, with the time it was sent (UTC+06:00, the same zone as the git history). Extracted mechanically from the session transcript; nothing was edited except that the harness markers around pasted text were removed.

Two further inputs were answers to multiple-choice questions the agent asked: **"Phase 2 then 3 (Recommended)"** (build order) and **"At-least-once (Recommended)"** (email delivery guarantee, [D-043](../DECISIONS.md)), plus "I'll connect it, then retry" (connecting the Chrome extension). The long course text pasted in rows 16 and 17 is shortened here to its first lines; the full text is the course statement.

Models: phases 0-10 ran on `claude-opus-5-5`; from row 11 on (2026-10-12 13:44+06:00) the session ran on `claude-sonnet-5-5`.

## 0. Phase 0 · 2026-10-11T09:44:40+06:00

````text
You are the lead architect on a university-level hiring assignment: "Task 9: Event registration service". It will be reviewed by engineers who care about correctness under concurrency, honest documentation, and proof that the system works. I am a junior fullstack dev (backend focus) and will build this with you phase by phase.

REQUIREMENTS (all mandatory)
- Separate backend (Python/FastAPI) and frontend (React + Vite) talking over the network. PostgreSQL. Local run via docker compose in one command. Email is emulated with Mailpit. Must work with two browser tabs open at once. Must prove it works (automated tests). Honest README of state.
- Event: description, date/time, seat limit. Participant registers by email, can cancel. Waitlist when full. Ticket with a code, and a check-in screen (typing the code replaces a scanner). Organizer screen: registered, waitlisted, checked-in counts.
- Behaviors: registration email with ticket; repeat registration with the same email never creates a second seat; when full, new registrations go to the waitlist; on cancellation the first in the waitlist automatically gets the seat and an email; two people for the last seat at the same moment -> one gets it, the other the waitlist; exactly one reminder to every participant 24h before the event; a ticket can be checked in only once and the organizer's arrived counter updates live; if the organizer reschedules the event, every participant gets an email.

YOUR JOB IN THIS PHASE (no application code yet)
1. Propose the architecture and justify every major choice in 1-2 sentences (libraries, sync vs async, ORM, migrations, scheduler approach, live updates SSE vs WebSocket, email delivery approach e.g. transactional outbox, auth model for organizer vs participants).
2. Design the data model (tables, columns, constraints, indexes, status enums, state machine for a registration: confirmed / waitlisted / cancelled / checked_in). Normalize emails. Define the unique constraints that enforce "one seat per email per event" at DB level.
3. For each tricky behavior, state the exact mechanism: last-seat race (locking strategy), waitlist promotion ordering (FIFO rule), exactly-once reminders and emails (idempotency, restart safety, what happens to reminders missed during downtime), reschedule (what happens to reminder state), check-in atomicity, live updates fan-out across multiple backend workers.
4. List edge cases and decide each one explicitly (e.g. re-registering after cancelling, registering for a past event, reducing the seat limit below current registrations, increasing it while people are waitlisted, cancel after check-in, event cancelled, promotion email failing).
5. Write the API contract (endpoints, request/response, error codes).
6. Write the phased plan (phases 1-10 below), each with: scope, files expected, tests that must pass (name them), and a "definition of done".
   1 Scaffold + infra, 2 Registration core + waitlist + locking, 3 Email outbox + tickets, 4 Check-in + organizer stats, 5 Live updates (SSE), 6 Scheduler: reminders + reschedule, 7 Frontend, 8 E2E and proof (two-tab test, concurrency stress), 9 Independent review/hardening, 10 Final docs.
7. Write a TEST_PLAN mapping every requirement above to at least one automated test.

OUTPUT FILES (create these, nothing else)
- CLAUDE.md: project rules for future sessions (stack, commands to run/test, coding conventions, "never claim done without running tests", "never skip a failing test", "log every decision in DECISIONS.md with timestamp", "append to DEVLOG.md at end of each phase", commit-per-phase rule).
- DECISIONS.md: initial entries with timestamps (use `date -Iseconds`) and reasons.
- DEVLOG.md: start entry.
- docs/ARCHITECTURE.md, docs/API.md, docs/PLAN.md, docs/TEST_PLAN.md
Then git init and commit as "phase 0: architecture and plan".

Before writing, ask me up to 5 questions only if a decision truly needs my input. Challenge any requirement that is ambiguous and state your assumption. Prefer boring, proven solutions over clever ones.


Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from `date -Iseconds`); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 1. Phase 1 · 2026-10-11T09:55:39+06:00

````text
Implement phase 1 from docs/PLAN.md. Create backend (FastAPI, SQLAlchemy 2 + Alembic, pytest with a real Postgres test DB), frontend (Vite + React, empty page that calls /health), docker-compose.yml (postgres, mailpit, backend, frontend), .env.example, Makefile (up, down, test, migrate, lint). Add GET /health including a DB check. Tests: health endpoint, migration up/down applies cleanly, compose boots from scratch with `make up`. README with a "quick start" section.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from `date -Iseconds`); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 2. Phase 2 · 2026-10-11T10:20:52+06:00

````text
Implement phase 2 from docs/PLAN.md: events CRUD (organizer only), registration, cancel, waitlist, FIFO promotion, normalized email, DB-level unique constraint, row-level locking on the event so concurrent register/cancel are serialized. First show me your plan and the locking strategy; wait for approval.
Tests (must be real concurrency tests against Postgres, not mocks): 1) 20 parallel registrations for 5 seats -> exactly 5 confirmed, 15 waitlisted; 2) two parallel for the last seat; 3) same email 10x in parallel -> one row; 4) email case/whitespace variants; 5) cancel promotes the first waitlisted, in order; 6) parallel cancels and registrations keep confirmed <= limit; 7) edge cases decided in docs/ARCHITECTURE.md. Run the concurrency tests 20 times in a loop to check for flakiness and show the result.


Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from `date -Iseconds`); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 3. Phase 3 · 2026-10-11T14:20:18+06:00

````text
Implement phase 3: a transactional outbox table written in the same transaction as the state change, and a worker that sends via SMTP to Mailpit with retry and an idempotency key so each email is sent exactly once. Ticket code: unguessable, unique. Emails: registration ticket, waitlist notice, promotion with ticket. Tests: one email per registration; repeat registration sends no second email; promotion sends exactly one email; worker restart mid-batch doesn't duplicate; SMTP failure retries and then sends once. Verify through the Mailpit API.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 4. Phase 4 · 2026-10-11T19:48:59+06:00

````text
Implement phase 4: POST check-in by ticket code as an atomic conditional UPDATE (only confirmed and not yet checked in), clear error codes for invalid / already used / cancelled / waitlisted. Organizer stats endpoint: confirmed, waitlisted, checked_in, free seats. Simple organizer auth as decided in ARCHITECTURE.md. Tests: double check-in sequentially and in parallel (exactly one success), wrong code, cancelled ticket, stats correctness after every kind of transition.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 5. Phase 5 · 2026-10-12T02:00:55+06:00

````text
Implement phase 5: SSE endpoints for the organizer stats and for the public event page (seats left). The mechanism must work with more than one backend worker (use the approach from ARCHITECTURE.md, e.g. Postgres LISTEN/NOTIFY). Handle client reconnect and send a snapshot on connect. Tests: two SSE clients both receive an update after a registration, a cancellation and a check-in; an event for another event doesn't leak; reconnect gets the current snapshot; run with 2 backend workers.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 6. Phase 6 · 2026-10-12T02:24:52+06:00

````text
Implement phase 6: a restart-safe scheduler (DB-driven, SELECT ... FOR UPDATE SKIP LOCKED, no in-memory-only timers) that sends exactly one reminder per confirmed participant 24h before the event, and a reschedule flow that emails all participants (confirmed and waitlisted, as decided in ARCHITECTURE.md) and recomputes reminder state. Implement the decided policy for reminders missed during downtime and for events created less than 24h ahead. Tests with a controllable clock: reminder sent once even with 3 scheduler instances running; not sent to cancelled or waitlisted; promoted participants get one; restart between claim and send doesn't lose or duplicate; reschedule resets correctly and the reminder follows the new date; moving the event into the past/near future.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 7. Phase 7 · 2026-10-12T03:14:39+06:00

````text
Implement phase 7 with React + Vite: public event page (details, seats left live, register form, result states confirmed/waitlisted/already registered, cancel via ticket), ticket page, organizer screen (create/edit/reschedule event, live counters, participant lists), check-in screen (code input, clear success/error states). Keep it clean and simple, with loading and error states. Component tests for the key states; no styling rabbit holes.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 8. Phase 8 · 2026-10-12T03:30:40+06:00

````text
Implement phase 8: Playwright tests with two browser contexts: register in tab A -> tab B's seat counter updates without reload; last-seat race through the UI; cancel promotes the waitlisted user (check Mailpit); check-in once, organizer counter live; reschedule sends emails. Add scripts/stress.py (e.g. 200 concurrent registrations) that prints invariants (confirmed <= limit, no duplicate emails). Add `make proof` that runs everything and prints a pass/fail table mapped to docs/TEST_PLAN.md.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 9. Phase 9 (review) · 2026-10-12T04:14:20+06:00

````text
Act as a skeptical senior reviewer who has never seen this project. Read the repo and docs/TEST_PLAN.md. Hunt for: race conditions, missing locks/constraints, non-idempotent email paths, timezone mistakes, SSE leaks, flaky tests, requirements without a real test, claims in the README that the code doesn't support. Do NOT fix anything yet: write docs/REVIEW.md with findings ranked by severity and a proposed test that reproduces each. Then fix the high-severity ones one by one, test first, one commit each.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 10. Phase 10 (README) · 2026-10-12T04:59:44+06:00

````text
Write the final README.md: what the project is, quick start (exact commands, prerequisites), architecture summary, what works, what doesn't or wasn't done and why, how to run the proof (`make proof`), AI tools used (model and tool, and why, 2 sentences), anything adapted from a template or generator, and next steps. Generate docs/TIMELINE.md from `git log --date=iso` and DEVLOG.md. Check that every claim in the README matches reality by running the commands. Don't invent anything.
Follow CLAUDE.md. When done: run the full test suite and show me the output; append decisions to DECISIONS.md and an entry to DEVLOG.md (timestamp from date -Iseconds); commit with message "phase N: <summary>"; then give me a 5-line summary of what works, what doesn't, and what is untested. Do not start the next phase.
````

## 11. Run the project for manual testing (model switched to Sonnet 5.5 just before) · 2026-10-12T13:44:45+06:00

````text
run the project and i will test it all manully run both backend and front end
````

## 12. Phase 7b (Stitch design) · 2026-10-12T19:35:18+06:00

````text
Read everything in docs/ (the Stitch export folder). Rebuild its UI and UX in our React + Vite frontend as a faithful visual copy: same layout, spacing, colors, typography, components, states, and navigation flow. Prefer reusing the exported CSS/Tailwind classes and structure over redesigning.

Hard rules:
1. NO dummy data. Remove every hardcoded name, number, date, image, speaker, price and text that comes from the design mockups. All content must come from our backend API (docs/API.md) and live updates from SSE. Show proper loading, empty and error states instead.
2. If a design element has no backend support (speakers, schedule, FAQ, pricing, revenue, map, VIP passes, etc.), remove it. Do not fake it and do not invent new API endpoints for it.
3. Screens to build: event page (live seats left, register form, confirmed/waitlist/already-registered states), ticket page (code + cancel), organizer screen (create/edit/reschedule, live counters, participant lists), check-in screen (code input, success/error states).
4. Keep our existing routing, API client and SSE logic. Change only the presentation layer.
5. Make it responsive like the design.

Steps: first list the design files and map each to our screen and component, and show me the mapping and the list of elements you will remove. Wait for my OK. Then implement, run the component and E2E tests, and fix anything that breaks. Log decisions in DECISIONS.md and DEVLOG.md, then commit as "phase 7b: apply Stitch design".
````

## 13. Approval of the 7b mapping · 2026-10-12T19:43:07+06:00

````text
OK
````

## 14. Browser test of the whole UI · 2026-10-12T20:20:19+06:00

````text
now use the claude in chrome to test everything with UI, i will just monitor u
````

## 15. Retry after connecting Chrome · 2026-10-12T20:24:46+06:00

````text
try again
````

## 16. Course requirements pasted, with the request to audit the project against them · 2026-10-12T21:13:10+06:00

````text
Требования [... course requirements 1-13 and Task 9, shortened ...]

now check if we meet all these requirements
````

## 17. Submission request: what the course expects · 2026-10-12T21:18:41+06:00

````text
Что мы ожидаем от вас [... the 7 deliverables, see docs/SUBMISSION.md ...]

now prepare these things for submission
````
