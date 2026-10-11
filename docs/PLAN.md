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
- **Scope:** `Broker` (LISTEN/NOTIFY, per-event subscriber queues, reconnect and resync), `pg_notify` in every mutating transaction (incl. email completions), public + organizer SSE endpoints with snapshot-on-connect, coalescing, keepalive, and session-expiry close. nginx streaming config. Uvicorn runs with 2 workers.
- **Files (as built):** `backend/app/live/{broker,sse}.py`, `backend/app/api/stream.py`, pure-ASGI `X-Backend-Pid` header (non-production), tests `tests/{test_live,sse,live_server}.py`.
- **Tests (as built; all against real uvicorn processes, see D-061):**
  - `test_live.py::test_public_stream_sends_snapshot_on_connect`, `::test_organizer_stream_sends_snapshot_on_connect`
  - `::test_two_clients_receive_registration_cancellation_and_checkin` (organizer + public streams on two separate backend processes; writes from a third)
  - `::test_update_reaches_every_worker_of_a_multi_worker_server` (`uvicorn --workers 2`, streams proven on both pids)
  - `::test_other_events_do_not_leak_into_a_stream`, `::test_broker_routes_signals_by_event_id`
  - `::test_reconnect_gets_current_snapshot`, `::test_listener_connection_loss_is_healed_and_resynced`, `::test_notification_only_on_commit`
  - `::test_email_delivery_updates_organizer_stream`, `::test_keepalive_comments_on_idle_stream`, `::test_stream_errors_are_json_before_streaming`, `::test_organizer_stream_ends_when_login_expires`, `::test_stream_releases_subscription_when_client_goes_away`
  - smoke: 6 SSE streams through nginx to the compose backend (2 workers) all receive a registration
- **DoD:** with the stack running, `curl -N localhost:8080/api/events/{id}/stream` prints a new frame within 1s of a change made via another terminal. ✅ The smoke test checks this on the real stack.

## Phase 6: Scheduler (reminders, reschedule, event cancel)
- **Scope:** DB-driven reminder scheduler (FOR UPDATE SKIP LOCKED per event, outbox dedupe key, re-arm of skipped), send-time reminder check in the dispatcher, reschedule (version bump, void pending reminders, emails), event cancel, catch-up semantics. The worker runs scheduler + dispatcher, and compose checks both heartbeats.
- **Files (as built):** `backend/app/scheduler.py`, `backend/app/emails/dispatcher.py` (`_prepare_reminder`), `backend/app/services/events.py` (`reschedule_event`, `cancel_event`), templates, routes, `backend/app/worker.py`; tests `tests/{test_reminders,test_reschedule,test_event_cancel}.py`, additions in `test_worker_process.py`, `test_live.py`, `test_outbox.py`.
- **Tests (as built):**
  - `test_reminders.py::test_reminder_sent_once_with_three_scheduler_instances`, `::test_three_schedulers_split_due_events_with_skip_locked` (gated), `::test_window_opens_exactly_24h_before`, `::test_not_sent_to_cancelled_or_waitlisted`, `::test_cancelled_after_enqueue_is_skipped_and_promoted_gets_one`, `::test_promoted_participant_gets_exactly_one`, `::test_dispatcher_restart_between_claim_and_send_neither_loses_nor_duplicates`, `::test_scheduler_crash_before_commit_loses_nothing`, `::test_late_reminder_after_downtime_if_event_not_started`, `::test_no_reminder_after_event_started`, `::test_event_created_less_than_24h_ahead`, `::test_cancel_and_reregister_gets_one_reminder`, `::test_skipped_reminder_is_rearmed_when_person_confirmed_again`, `::test_checked_in_before_reminder_is_skipped`, `::test_tick_without_due_events_is_a_noop`, `::test_reminder_key_is_per_person_per_schedule_version`
  - `test_reschedule.py::test_reschedule_emails_every_participant`, `::test_reschedule_resets_reminders_and_reminder_follows_new_date`, `::test_reschedule_voids_pending_reminders`, `::test_reminder_claimed_before_reschedule_is_not_sent_with_old_date`, `::test_reschedule_into_near_future_sends_new_reminder_next_tick`, `::test_reschedule_into_past_rejected`, `::test_reschedule_same_time_is_noop`, `::test_reschedule_after_start_reopens_registration`, `::test_reschedule_errors`
  - `test_event_cancel.py::test_cancel_event_notifies_and_blocks_actions`, `::test_cancel_event_idempotent`, `::test_cancel_event_requires_organizer`
  - `test_worker_process.py::test_three_worker_processes_send_each_reminder_once` (3 real worker processes)
  - `test_live.py::test_reschedule_and_event_cancel_reach_public_stream`; `test_outbox.py::test_enqueue_reports_whether_a_row_was_written`
  - smoke: real worker scheduler sends exactly 1 reminder; reschedule gives 1 "New date" email + 1 reminder for the new date
- **DoD:** all pass. The manual demo is replaced by the smoke probe on the real stack (an event 23h ahead gets exactly one reminder in Mailpit). ✅

## Phase 7: Frontend
- **Scope:** pages:
  - events list;
  - event page (details, live seats left, register form, outcomes confirmed / waitlisted / already registered, errors);
  - ticket page `/r/:token` (ticket code, waitlist position, checked-in and cancelled states, cancel);
  - organizer login + guard, events list + create, dashboard (live counters, participant list with status tabs, edit, reschedule, cancel event);
  - check-in (autofocus, Enter submits, big green/red result per error code, input cleared on success / selected on error).

  Error `code` → human message map. Loading and error state on every page.
- **Files (as built):** `frontend/src/{api.ts,errors.ts,format.ts,useEventStream.ts,App.tsx,index.css}`, `frontend/src/components/ui.tsx`, `frontend/src/pages/{EventsList,EventPage,TicketPage}.tsx`, `frontend/src/pages/admin/{RequireOrganizer,AdminLogin,AdminEvents,AdminDashboard,CheckIn}.tsx`, tests `*.test.tsx`, helpers `frontend/src/test/{fakes.ts,render.tsx}`.
- **Tests (Vitest, as built; render the real route table with mocked fetch + fake EventSource):**
  - `App.test.tsx::renders_app_shell`, `::calls_api_health_and_shows_ok`, `::shows_db_down_on_503`, `::lists_upcoming_events_with_links`
  - `EventPage.test.tsx::shows_details_and_seats_left_updating_live`, `::shows_confirmed_after_register`, `::shows_waitlist_position_when_full`, `::shows_already_registered_without_a_second_seat`, `::shows_error_for_closed_registration`, `::shows_error_for_invalid_email`, `::hides_form_for_cancelled_event`, `::shows_not_found_error`
  - `TicketPage.test.tsx::shows_ticket_code_and_cancels`, `::does_nothing_if_cancel_not_confirmed`, `::shows_waitlist_position_without_code`, `::shows_checked_in_state_without_cancel`, `::shows_error_when_cancel_fails`, `::shows_invalid_link`
  - `CheckIn.test.tsx::success_clears_input_and_shows_green`, `::already_checked_in_shows_red_with_time`, `::error_<code>_has_its_own_message` (×5), `::shows_live_arrived_counter`
  - `AdminDashboard.test.tsx::renders_live_counts_and_refreshes_participants`, `::filters_participants_by_status`, `::reschedules_with_iso_time_and_reports_notified`, `::shows_capacity_error_with_seats_taken`, `::asks_to_log_in_again_when_stream_session_expires`
  - `AdminAccess.test.tsx::redirects_to_login_then_back_after_login`, `::creates_event_with_iso_time_and_opens_dashboard`
  - `useEventStream.test.ts::applies_snapshots_and_reconnects`, `::reports_closed_when_server_refuses`, `::stops_on_session_expired`, `::closes_on_unmount_and_ignores_other_events`, `::does_not_connect_without_url`
- **DoD:** every user-facing flow in the brief is clickable in the browser on `localhost:8080`. Tests, `tsc` and eslint are clean. ✅ A manual two-tab walkthrough on the real stack is recorded in DEVLOG phase 7.

## Phase 8: E2E and proof
- **Scope:**
  - Playwright suite (official image, Chromium) in **two browser contexts**, against an isolated compose stack (scheduler tick 2s), reading real emails through that stack's Mailpit API.
  - `scripts/stress.py` against the running stack through nginx (2 workers), with printed invariants.
  - `make proof` runs everything and prints a requirement table generated from the JUnit results.
- **Files (as built):** `e2e/{package.json,package-lock.json,playwright.config.ts,tsconfig.json,Dockerfile}`, `e2e/tests/{helpers,two_tabs.spec,registration.spec,waitlist.spec,checkin.spec,reschedule.spec,reminder.spec}.ts`, `scripts/{e2e.sh,stress.py,proof.sh,proof_report.py}`, compose service `e2e` (profile e2e), Makefile `e2e`, `stress`, `proof`.
- **Tests (as built):**
  - `two_tabs.spec.ts::register_in_tab_a_updates_seat_counter_in_tab_b_live`, `::checkin_in_tab_b_updates_organizer_counter_in_tab_a_live`, `::two_participants_race_for_last_seat_one_confirmed_one_waitlisted` (3 rounds)
  - `registration.spec.ts::register_receive_ticket_email_and_view_ticket`, `::duplicate_registration_no_second_seat_no_second_email`
  - `waitlist.spec.ts::full_event_waitlists_then_promotes_on_cancel_with_email` (real confirm dialog; promotion email from Mailpit, its link shows the ticket)
  - `checkin.spec.ts::second_checkin_rejected`
  - `reschedule.spec.ts::reschedule_emails_every_participant` (via dashboard UI; public tab shows the new date live)
  - `reminder.spec.ts::event_23h_ahead_gets_exactly_one_reminder`
  - `scripts/stress.py`: 200 distinct + 10×5 duplicate registrations at once on a 50-seat event, then 20 cancels + 30 registrations at once. 17 invariants: confirmed ≤ limit, no duplicate emails, no free seat while people wait, positions 1..n, API = list, FIFO promotion, no queue jumping, all 2xx. Exit 1 on any violation.
- **DoD:** `make proof` passes with every TEST_PLAN row PASS except the manual P7. E2E passed 3 consecutive times on fresh stacks (`scripts/e2e.sh` always starts from `down -v`). Results are pasted into DEVLOG.

## Phase 9: Independent review and hardening
- **Scope:** a fresh-context reviewer (separate agent session, or `/code-review high`) audits concurrency, transactions, error handling, security (cookie flags, token leakage, CSRF, SQL injection, PII in public endpoints, logging of secrets) and docs-vs-code drift. Every finding is fixed with a regression test or explicitly rejected with a reason.
- **Files:** `docs/REVIEW.md` (findings table: id, severity, status, test), plus fixes.
- **Tests:** one new regression test per fixed bug, named `test_review_<id>_<desc>`. Full suite and E2E green.
  - H1: `test_review.py::test_review_h1_unsendable_email_fails_alone_and_others_are_delivered`, `::test_review_h1_title_with_control_characters_rejected`, `::test_review_h1_unexpected_error_in_one_row_does_not_block_batch`
  - H2: `test_review.py::test_review_h2_manage_token_not_in_backend_logs` plus a smoke probe (nginx)
- **DoD:** REVIEW.md has no open high or medium findings. Full suite and E2E were re-run and shown.

## Phase 10: Final docs
- **Scope:** final README (what it is, quick start with prerequisites, architecture summary, what works with evidence, what doesn't and why, proof, AI tools, templates, next steps), generated `docs/TIMELINE.md`, every README claim checked by running it.
- **Files (as built):** `README.md`, `docs/TIMELINE.md` (generated), `scripts/timeline.sh`, Makefile `help` fix.
- **Verification (as run):**
  - **Default ports on the dev stack:** :8080, :8080/api/health, :8000/api/health, :8000/health, :8000/docs and :8025 return 200; `pg_isready` on :5433 succeeds; the `curl -N …/stream` example prints `retry:` and an `availability` frame.
  - **Clean `git clone`** (with the phase 10 edits overlaid), own compose project and ports so the dev stack isn't touched:
    - `make up` creates `.env` and is healthy in 24s (warm cache);
    - `docker compose up --build -d --wait` **without make and without `.env`** is healthy in 14s;
    - **`make proof` passes in 243s: 245/245 test cases, 45 PASS + 1 MANUAL.**
  - Every relative link in the README and docs resolves (scripted check).
- **DoD:** a reviewer can go from `git clone` to a working demo using only the README, and every README claim is backed by a test, a command that was run, or is explicitly marked untested or open. ✅
