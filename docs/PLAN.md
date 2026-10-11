# Phased Plan

The rules from `CLAUDE.md` apply to every phase. A phase is **done** only when all of these hold:
1. Every test named in that phase exists and passes, along with all earlier tests. No `skip` or `xfail` without an entry in DECISIONS.md.
2. `ruff check`, `ruff format --check` and `mypy` are clean for backend changes. `eslint` and `tsc --noEmit` are clean for frontend changes.
3. The full test output has been run and shown.
4. `DECISIONS.md` and `DEVLOG.md` are updated, and there is one commit `phase N: <summary>`.

Test file paths are relative to `backend/tests/`, `frontend/src/`, or `e2e/`.

---

## Phase 0: Architecture and plan ✅ (this commit)
- **Scope:** design docs only.
- **Files:** `CLAUDE.md`, `DECISIONS.md`, `DEVLOG.md`, `docs/{ARCHITECTURE,API,PLAN,TEST_PLAN}.md`.
- **Tests:** none (there's no code yet).
- **DoD:** the docs are committed, and every requirement maps to a planned test in TEST_PLAN.

## Phase 1: Scaffold and infra
- **Scope:** compose stack boots with one command. FastAPI app with `/api/health`. Alembic baseline migration with **all three tables, enums, constraints and indexes** from ARCHITECTURE §5. Frontend skeleton served by nginx with the `/api` proxy. Injectable `Clock`. Test DB fixture (real Postgres, truncate between tests). Makefile. Compose smoke test. *(Changed during phase 1: the worker stub moved to phase 3 (D-023), and the test-DB init script is `infra/db/init-test-db.sh` (D-029).)*
- **Files:** `docker-compose.yml`, `.env.example`, `Makefile`, `infra/db/init-test-db.sh` (creates the `eventreg_test` DB), `scripts/smoke_compose.sh`, `backend/{Dockerfile,pyproject.toml,requirements.txt,requirements-dev.txt,alembic.ini}`, `backend/alembic/versions/0001_initial.py`, `backend/app/{__init__,main,config,db,models,clock}.py`, `backend/app/api/health.py`, `backend/tests/{conftest.py,test_health.py,test_schema.py}`, `frontend/{Dockerfile,nginx.conf,package.json,vite.config.ts,tsconfig.json,index.html}`, `frontend/src/{main.tsx,App.tsx,App.test.tsx,api.ts}`, `README.md` (stub with run instructions).
- **Tests:**
  - `test_health.py::test_health_ok`
  - `test_health.py::test_health_reports_db_error_as_503`
  - `test_schema.py::test_migrations_upgrade_downgrade_upgrade`
  - `test_schema.py::test_active_email_unique_index_rejects_second_active_row`
  - `test_schema.py::test_active_email_unique_index_allows_cancelled_duplicates`
  - `test_schema.py::test_seats_taken_check_rejects_overbooking`
  - `test_schema.py::test_checked_in_requires_timestamp`
  - `test_schema.py::test_outbox_dedupe_key_unique`
  - `test_schema.py::test_models_match_migrations` (added: ORM vs migration drift)
  - `test_schema.py::test_waitlisted_requires_queue_seq`, `::test_email_normalized_must_be_lowercase`, `::test_ticket_code_format_enforced` (added)
  - `test_health.py::test_health_db_timeout_returns_503_within_budget` (added)
  - `App.test.tsx::renders_app_shell`, `::calls_api_health_and_shows_ok`, `::shows_db_down_on_503`, `::shows_unreachable_on_network_error`
  - `scripts/smoke_compose.sh` (`make test-smoke`): `make up` from scratch in an isolated project, 7 probes
- **DoD:** `docker compose up --build` from a clean clone brings all 6 services to healthy, and `http://localhost:8080` shows the shell. `curl localhost:8080/api/health` returns ok. Mailpit UI is on `:8025`. `make test` passes.

## Phase 2: Registration core, waitlist and locking
- **Scope:** email normalization, ticket code and manage token generation, the services `register`, `cancel`, `update_event` (capacity incl. promotion and the below-taken rejection), organizer login/cookie, admin create/list/patch events, public events endpoints, participant view/cancel. Event-row lock, FIFO promotion, invariants. Outbox rows are **inserted** in this phase (needed for atomicity) but not sent yet.
- **Files:** `backend/app/{security.py,errors.py,schemas.py}`, `backend/app/services/{registration.py,events.py,codes.py,emails_enqueue.py}`, `backend/app/api/{events.py,registrations.py,admin.py}`, tests below.
- **Tests:**
  - `test_normalize.py::test_email_normalized_trim_lower`, `::test_invalid_email_rejected`
  - `test_codes.py::test_ticket_code_alphabet_and_length`, `::test_code_input_normalization`, `::test_code_collision_retries`
  - `test_registration.py::test_register_confirms_when_seat_available`
  - `::test_register_waitlists_when_full`
  - `::test_duplicate_email_returns_existing_no_second_row`
  - `::test_duplicate_email_case_and_whitespace_variants`
  - `::test_reregister_after_cancel_creates_new_row_back_of_queue`
  - `::test_register_past_event_rejected`
  - `::test_register_cancelled_event_rejected`
  - `::test_response_never_contains_ticket_or_token`
  - `test_cancel.py::test_cancel_confirmed_promotes_first_waitlisted`
  - `::test_promotion_is_fifo_by_queue_seq`
  - `::test_cancel_waitlisted_does_not_promote`
  - `::test_cancel_is_idempotent`
  - `::test_cancel_after_event_start_rejected`
  - `::test_cancel_invalid_token_404`
  - `test_capacity.py::test_increase_capacity_promotes_fifo`
  - `::test_decrease_below_taken_rejected`
  - `::test_decrease_to_taken_allowed`
  - `test_admin_auth.py::test_admin_endpoints_require_cookie`, `::test_login_wrong_password_401`, `::test_login_sets_httponly_samesite_cookie`
  - `test_concurrency.py::test_last_seat_race_one_confirmed_one_waitlisted` (2 concurrent, repeated 25×)
  - `::test_concurrent_registrations_never_overbook` (capacity 10, 100 concurrent distinct emails)
  - `::test_concurrent_same_email_creates_one_row` (20 concurrent, same email)
  - `::test_concurrent_cancel_and_register_respects_waitlist_order`
  - `::test_invariants_hold_after_stress` (seats_taken == count, no idle seat while waitlist non-empty, queue_seq unique)
- **Added during implementation:** `test_concurrency.py::test_20_parallel_registrations_5_seats`, `::test_100_parallel_registrations_10_seats_never_overbook`, `::test_concurrent_same_email_creates_one_row[identical|case_whitespace_variants]`, `::test_parallel_cancels_and_registrations_keep_invariants` (replaces `test_concurrent_cancel_and_register_respects_waitlist_order` and `test_invariants_hold_after_stress`; invariants are checked after every concurrency test). Also `test_cancel.py::test_cancel_after_checkin_rejected`, `::test_cancel_on_cancelled_event_rejected`, `::test_get_registration_shows_ticket_only_when_confirmed`; `test_capacity.py` covers create/read/update validation and the public list (incl. `::test_capacity_change_after_start_rejected`, `::test_update_cancelled_event_rejected`); `test_codes.py::test_ticket_codes_look_random`; `test_admin_auth.py::test_tampered_cookie_rejected`, `::test_logout_clears_cookie`.
- **DoD:** all of the above pass against real Postgres. Concurrency tests use separate connections (not a shared session) and passed **20 consecutive runs** (`make test-concurrency-loop N=20`, user's requirement; replaces the pytest-repeat ×5 idea).

## Phase 3: Email outbox dispatcher and tickets
- **Scope:** `worker` compose service (moved here from phase 1, D-023). Worker dispatcher loop (claim with SKIP LOCKED, lease, retry/backoff, max attempts → failed), SMTP via aiosmtplib to Mailpit, templates for all email kinds, Message-ID from dedupe key, reminder send-time guard hook. Participant view shows the ticket code.
- **Files:** `backend/app/outbox/{dispatcher.py,templates.py,smtp.py}`, `backend/app/worker.py` (real loop), tests.
- **Files (as built):** `backend/app/emails/{dispatcher,smtp,templates,outbox}.py`, `backend/app/worker.py`, compose services `worker` + `mailpit-test`; tests `tests/{test_email_delivery,test_outbox,test_worker_process}.py`, helpers `tests/{mailpit,senders}.py`.
- **Tests (as built; user's phase 3 list first):**
  - `test_email_delivery.py::test_one_email_per_registration`, `::test_repeat_registration_sends_no_second_email`, `::test_promotion_sends_exactly_one_email_with_ticket`, `::test_worker_restart_mid_batch_does_not_duplicate`, `::test_smtp_failure_retries_then_sends_once`, `::test_known_window_crash_after_smtp_accept_resends_same_message_id`
  - `test_worker_process.py::test_sigterm_mid_batch_then_restart_sends_each_email_once`, `::test_sigkill_mid_batch_then_restart_delivers_all_at_most_one_duplicate` (real `python -m app.worker` processes)
  - `test_outbox.py::test_ticket_email_enqueued_in_same_tx_as_registration`, `::test_backoff_is_exponential_and_capped`, `::test_lease_must_exceed_batch_send_time`, `::test_dispatch_marks_failed_after_max_attempts`, `::test_failed_promotion_email_keeps_seat`, `::test_two_dispatchers_never_send_same_row`, `::test_stale_claim_cannot_overwrite_newer_claim`, `::test_concurrent_claims_are_disjoint`, `::test_graceful_stop_releases_unsent_rows`, `::test_message_headers`
- **DoD:** registering through the API produces a real email in the Mailpit UI with a ticket code and a working manage link. The Mailpit-outage case was demonstrated: stop mailpit, register, start mailpit, the email arrives. ✅ Both done; the smoke test checks the first, and DEVLOG phase 3 records the second. (The manage link points at the `/r/{token}` page, which the UI builds in phase 7. The API behind it works now.)

## Phase 4: Check-in and organizer stats
- **Scope:** check-in endpoint (atomic conditional update), code normalization, stats endpoint, registrations list.
- **Files (as built):** `backend/app/services/{checkin,stats}.py`, `backend/app/timefmt.py`, routes in `backend/app/api/admin.py`, tests `tests/{test_checkin,test_stats}.py`, `tests/concurrency.py::row_lock_gate`.
- **Tests (as built):**
  - `test_checkin.py::test_checkin_success`, `::test_checkin_twice_sequential_second_is_409_with_original_time`, `::test_concurrent_checkin_same_code_exactly_one_succeeds` (10 gated scanners × 10 rounds), `::test_concurrent_checkins_of_different_tickets_all_succeed`, `::test_checkin_wrong_code_404`, `::test_checkin_malformed_code_422`, `::test_checkin_cancelled_ticket_rejected`, `::test_checkin_waitlisted_ticket_rejected`, `::test_promoted_ticket_can_check_in`, `::test_checkin_other_event_code_404`, `::test_checkin_normalizes_input`, `::test_cancel_after_checkin_rejected`, `::test_checkin_vs_cancel_race_exactly_one_wins[checkin|cancel]`, `::test_checkin_cancelled_event_rejected`, `::test_checkin_unknown_event_404`, `::test_checkin_requires_organizer`
  - `test_stats.py::test_stats_after_every_kind_of_transition` (17 steps, explicit expected numbers + independent recount), `::test_stats_email_counts`, `::test_stats_never_inconsistent_during_concurrent_writes`, `::test_stats_unknown_event_404`, `::test_stats_requires_admin`, `::test_registrations_list_order_filter_and_positions`
- **DoD:** tests pass. Counts in stats match direct SQL counts after a mixed scenario. ✅ Concurrency subset passed 20/20 runs. The check-in guard was mutation-checked.

## Phase 5: Live updates (SSE)
- **Scope:** `Broker` (LISTEN/NOTIFY, per-event subscriber queues, reconnect and resync), `pg_notify` in every mutating transaction, SSE endpoint with snapshot-on-connect, coalescing and keepalive. nginx streaming config. Uvicorn runs with 2 workers.
- **Files:** `backend/app/live/{broker.py,sse.py}`, `backend/app/api/stream.py`, `frontend/nginx.conf` update, tests.
- **Tests:**
  - `test_live.py::test_stream_sends_snapshot_on_connect`
  - `::test_checkin_pushes_update_to_stream`
  - `::test_registration_pushes_update_to_stream`
  - `::test_notify_not_delivered_on_rollback`
  - `::test_fanout_across_two_brokers` (two independent Broker instances = two processes; a write on one connection reaches both)
  - `::test_broker_reconnect_triggers_resync`
  - `::test_stream_unknown_event_404`
  - `test_live_multiworker.py::test_update_reaches_client_on_other_uvicorn_worker` (against the running compose backend with 2 workers: open 4 streams, check in, all 4 receive the update)
- **DoD:** with the stack running, `curl -N localhost:8080/api/events/{id}/stream` prints a new `stats` frame within 1s of a check-in made via another terminal.

## Phase 6: Scheduler (reminders, reschedule, event cancel)
- **Scope:** reminder tick (INSERT…SELECT…ON CONFLICT DO NOTHING), reminder send-time guard, reschedule endpoint (version bump and emails), cancel-event endpoint, catch-up semantics.
- **Files:** `backend/app/scheduler.py`, `backend/app/services/events.py` (reschedule/cancel), tests.
- **Tests:**
  - `test_reminders.py::test_reminder_enqueued_inside_24h_window`
  - `::test_no_reminder_outside_window`
  - `::test_tick_twice_enqueues_once`
  - `::test_two_schedulers_concurrently_enqueue_once`
  - `::test_reminder_only_for_confirmed_not_waitlisted_or_cancelled`
  - `::test_late_reminder_after_downtime_if_event_not_started`
  - `::test_no_reminder_after_event_started`
  - `::test_cancel_reregister_same_email_gets_one_reminder`
  - `::test_promoted_inside_window_gets_reminder_next_tick`
  - `::test_stale_reminder_skipped_after_cancel`
  - `test_reschedule.py::test_reschedule_emails_confirmed_and_waitlisted_not_cancelled`
  - `::test_reschedule_bumps_version_and_voids_pending_reminder`
  - `::test_reschedule_after_reminder_sent_sends_one_new_reminder`
  - `::test_reschedule_same_time_is_noop`
  - `::test_reschedule_to_past_rejected`
  - `::test_reschedule_email_arrives_in_mailpit` (integration)
  - `test_event_cancel.py::test_cancel_event_notifies_and_blocks_actions`
  - `::test_cancel_event_idempotent`
- **DoD:** all pass. A manual demo of creating an event 23h ahead, registering, and seeing the reminder in Mailpit within one tick was done and recorded in DEVLOG.

## Phase 7: Frontend
- **Scope:** pages: events list; event page with register form (shows confirmed or waitlisted with position); manage page `/r/:token` (ticket code, cancel); admin login; admin events list + create; admin event dashboard (live counters via EventSource, registrations table, capacity edit, reschedule, cancel event); check-in page (autofocus input, Enter submits, big green/red result, input cleared for next ticket). Error `code` → human message map.
- **Files:** `frontend/src/{api.ts,useEventStream.ts,errors.ts}`, `frontend/src/pages/{EventsList,EventPage,ManagePage,AdminLogin,AdminEvents,AdminDashboard,CheckIn}.tsx`, `*.test.tsx`.
- **Tests (Vitest):**
  - `EventPage.test.tsx::shows_confirmed_after_register`, `::shows_waitlist_position_when_full`, `::shows_error_for_closed_registration`
  - `ManagePage.test.tsx::shows_ticket_code_and_cancels`
  - `CheckIn.test.tsx::success_clears_input_and_shows_green`, `::already_checked_in_shows_red_with_time`
  - `useEventStream.test.ts::applies_snapshots_and_reconnects`
  - `AdminDashboard.test.tsx::renders_live_counts`
- **DoD:** every user-facing flow in the brief is clickable in the browser on `localhost:8080`. Tests, `tsc` and eslint are clean.

## Phase 8: E2E and proof
- **Scope:** Playwright suite against the running compose stack, reading real emails through the Mailpit API. A load/stress script for the concurrency claim with printed results. CI-style one-liner `make e2e`.
- **Files:** `e2e/{package.json,playwright.config.ts}`, `e2e/tests/*.spec.ts`, `e2e/helpers/mailpit.ts`, `scripts/stress_last_seat.py`.
- **Tests:**
  - `registration.spec.ts::register_receive_ticket_email_and_view_ticket`
  - `registration.spec.ts::duplicate_registration_no_second_seat_no_second_email`
  - `waitlist.spec.ts::full_event_waitlists_then_promotes_on_cancel_with_email`
  - `two_tabs.spec.ts::checkin_in_tab_b_updates_organizer_counter_in_tab_a_live` (two browser contexts, no reload)
  - `two_tabs.spec.ts::two_participants_race_for_last_seat_one_confirmed_one_waitlisted`
  - `checkin.spec.ts::second_checkin_rejected`
  - `reschedule.spec.ts::reschedule_emails_every_participant`
  - `reminder.spec.ts::event_23h_ahead_gets_exactly_one_reminder` (worker tick set to 2s in the test env, then waits 3 ticks and asserts the count is still 1)
  - `scripts/stress_last_seat.py`: 200 concurrent HTTP registrations for capacity 50 against the real stack. Prints confirmed/waitlisted counts and runs the invariant SQL. The exit code is non-zero on any violation.
- **DoD:** `make e2e` passes 3 consecutive times on a fresh `docker compose down -v && up`. The stress output is pasted into DEVLOG.

## Phase 9: Independent review and hardening
- **Scope:** a fresh-context reviewer (separate agent session, or `/code-review high`) audits concurrency, transactions, error handling, security (cookie flags, token leakage, CSRF, SQL injection, PII in public endpoints, logging of secrets) and docs-vs-code drift. Every finding is fixed with a regression test or explicitly rejected with a reason.
- **Files:** `docs/REVIEW.md` (findings table: id, severity, status, test), plus fixes.
- **Tests:** one new regression test per fixed bug, named `test_review_<id>_<desc>`. Full suite and E2E green.
- **DoD:** REVIEW.md has no open high or medium findings. Full suite and E2E were re-run and shown.

## Phase 10: Final docs
- **Scope:** README with one-command run, demo walkthrough (URLs, organizer password from `.env.example`, how to see emails), architecture summary linking docs, **honest status** (what works, known limitations such as at-least-once SMTP, no rate limiting, single organizer), test commands and the latest real test output summary, a requirement→test table (from TEST_PLAN). Docs are checked against the code.
- **Files:** `README.md`, touch-ups in `docs/*`.
- **Tests:** full suite and E2E once more on a clean clone (`git clone` into a temp dir, then `docker compose up --build`, then `make test e2e`).
- **DoD:** a reviewer can go from `git clone` to a working demo using only the README. Every claim in the README is backed by a test or explicitly marked untested.
