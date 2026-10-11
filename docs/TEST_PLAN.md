# Test Plan: Requirement → Automated Test

Every mandatory requirement maps to at least one automated test. Test names match `docs/PLAN.md`. Status: **planned (phase 0)**. The *Phase* column says where each test is written. This table is copied into the README in phase 10 with real pass/fail status.

**Test layers**
- **Unit / service** (`backend/tests`, pytest, real Postgres `eventreg_test`): fast, direct service calls or the ASGI client, with time controlled by an injected `Clock`.
- **Integration** (`backend/tests/test_email_delivery.py`, `test_outbox.py`, `test_worker_process.py`, `test_live_multiworker.py`): real SMTP to a dedicated test Mailpit (`mailpit-test`), verified via its HTTP API; real `python -m app.worker` processes; the running compose backend.
- **Frontend** (Vitest + Testing Library): components with mocked `fetch`/`EventSource`.
- **E2E** (`e2e/`, Playwright): the full compose stack, real browser contexts, emails read from the Mailpit HTTP API.
- **Stress** (`scripts/stress_last_seat.py`): concurrent HTTP against the real stack, with SQL invariant checks.

## Platform requirements

| ID | Requirement | Test(s) | Phase |
|---|---|---|---|
| P1 | Separate backend (FastAPI) and frontend (React+Vite) talking over the network | `test_health.py::test_health_ok`; `App.test.tsx::calls_api_health_and_shows_ok`; smoke probe "frontend /api/health (nginx → backend over compose network)". E2E: every spec drives the UI on :8080, which calls the backend container through the nginx proxy | 1, 8 |
| P2 | PostgreSQL | `test_schema.py::test_migrations_upgrade_downgrade_upgrade`, `::test_models_match_migrations` (and the whole suite runs on Postgres) | 1 |
| P3 | One-command local run via docker compose | `scripts/smoke_compose.sh` (`make test-smoke`): runs `make up` on fresh volumes in an isolated project, then probes backend, nginx proxy, SPA, Mailpit, migration head and test DB. Phase 10 DoD repeats it from a clean clone | 1, 10 |
| P4 | Email emulated with Mailpit | `test_email_delivery.py::test_one_email_per_registration`; smoke probe "worker delivered exactly 2 emails"; E2E `registration.spec.ts` | 3, 8 |
| P5 | Works with two browser tabs at once | `test_live.py::test_two_clients_receive_registration_cancellation_and_checkin` (two clients, API level); `two_tabs.spec.ts::checkin_in_tab_b_updates_organizer_counter_in_tab_a_live`, `two_tabs.spec.ts::two_participants_race_for_last_seat_one_confirmed_one_waitlisted` | 8 |
| P6 | Proof it works (automated tests) | This whole plan. `make test` and `make e2e` | all |
| P7 | Honest README of state | Not automatable. Phase 9 review checks README claims against tests | 9, 10 |

## Domain requirements

| ID | Requirement | Test(s) | Phase |
|---|---|---|---|
| D1 | Event has description, date/time, seat limit | `test_schema.py::test_seats_taken_check_rejects_overbooking`; admin create covered in `test_capacity.py`; `AdminDashboard.test.tsx::renders_live_counts` | 1, 2, 7 |
| D2 | Participant registers by email | `test_registration.py::test_register_confirms_when_seat_available`; `EventPage.test.tsx::shows_confirmed_after_register` | 2, 7 |
| D3 | Participant can cancel | `test_cancel.py::test_cancel_confirmed_promotes_first_waitlisted`, `::test_cancel_is_idempotent`; `ManagePage.test.tsx::shows_ticket_code_and_cancels` | 2, 7 |
| D4 | Waitlist when full | `test_registration.py::test_register_waitlists_when_full`; `EventPage.test.tsx::shows_waitlist_position_when_full` | 2, 7 |
| D5 | Ticket with a code | `test_codes.py::test_ticket_code_alphabet_and_length`, `::test_ticket_codes_look_random`, `::test_code_collision_retries`; `test_schema.py::test_ticket_code_format_enforced`; `test_email_delivery.py::test_one_email_per_registration` | 2, 3 |
| D6 | Check-in screen: typing the code replaces a scanner | `test_checkin.py::test_checkin_success`, `::test_checkin_normalizes_input`; `CheckIn.test.tsx::success_clears_input_and_shows_green`; E2E `checkin.spec.ts` | 4, 7, 8 |
| D7 | Organizer screen: registered, waitlisted, checked-in counts | `test_stats.py::test_stats_after_every_kind_of_transition`, `::test_stats_never_inconsistent_during_concurrent_writes`, `::test_registrations_list_order_filter_and_positions`; `AdminDashboard.test.tsx::renders_live_counts` | 4, 7 |

## Behaviour requirements

| ID | Requirement | Test(s) | Phase |
|---|---|---|---|
| B1 | Registration email with ticket | `test_outbox.py::test_ticket_email_enqueued_in_same_tx_as_registration` (rollback leaves neither seat nor email); `test_email_delivery.py::test_one_email_per_registration` (ticket code + manage link in Mailpit; waitlist notice without code); E2E `registration.spec.ts::register_receive_ticket_email_and_view_ticket` | 3, 8 |
| B2 | Repeat registration with the same email never creates a second seat | `test_schema.py::test_active_email_unique_index_rejects_second_active_row` (DB level); `test_registration.py::test_duplicate_email_returns_existing_no_second_row`, `::test_duplicate_email_case_and_whitespace_variants`, `test_email_delivery.py::test_repeat_registration_sends_no_second_email` (Mailpit: 1 message after 5 variants, 2 workers); `test_concurrency.py::test_concurrent_same_email_creates_one_row[identical]`, `[case_whitespace_variants]`; E2E `registration.spec.ts::duplicate_registration_no_second_seat_no_second_email` | 1, 2, 3, 8 |
| B3 | When full, new registrations go to the waitlist | `test_registration.py::test_register_waitlists_when_full`; `test_concurrency.py::test_20_parallel_registrations_5_seats`, `::test_100_parallel_registrations_10_seats_never_overbook` | 2 |
| B4 | On cancellation, the first in the waitlist automatically gets the seat and an email | `test_cancel.py::test_cancel_confirmed_promotes_first_waitlisted`, `::test_promotion_is_fifo_by_queue_seq`; `test_concurrency.py::test_parallel_cancels_and_registrations_keep_invariants`; `test_email_delivery.py::test_promotion_sends_exactly_one_email_with_ticket`; `test_outbox.py::test_failed_promotion_email_keeps_seat`; E2E `waitlist.spec.ts::full_event_waitlists_then_promotes_on_cancel_with_email` | 2, 3, 8 |
| B5 | Two people for the last seat at the same moment: one gets it, the other the waitlist | `test_concurrency.py::test_last_seat_race_one_confirmed_one_waitlisted` (25 gated rounds), `::test_20_parallel_registrations_5_seats`, `::test_parallel_cancels_and_registrations_keep_invariants` (invariants checked after every concurrency test); `test_schema.py::test_seats_taken_check_rejects_overbooking`; E2E `two_tabs.spec.ts::two_participants_race_for_last_seat_one_confirmed_one_waitlisted`; `scripts/stress_last_seat.py` | 1, 2, 8 |
| B6 | Exactly one reminder to every participant 24h before the event | `test_reminders.py::test_reminder_enqueued_inside_24h_window`, `::test_no_reminder_outside_window`, `::test_tick_twice_enqueues_once`, `::test_two_schedulers_concurrently_enqueue_once`, `::test_reminder_only_for_confirmed_not_waitlisted_or_cancelled`, `::test_late_reminder_after_downtime_if_event_not_started`, `::test_no_reminder_after_event_started`, `::test_cancel_reregister_same_email_gets_one_reminder`, `::test_promoted_inside_window_gets_reminder_next_tick`, `::test_stale_reminder_skipped_after_cancel`; `test_outbox.py::test_concurrent_claims_are_disjoint`, `::test_two_dispatchers_never_send_same_row`; E2E `reminder.spec.ts::event_23h_ahead_gets_exactly_one_reminder` | 3, 6, 8 |
| B7a | A ticket can be checked in only once | `test_checkin.py::test_checkin_twice_sequential_second_is_409_with_original_time`, `::test_concurrent_checkin_same_code_exactly_one_succeeds`, `::test_checkin_vs_cancel_race_exactly_one_wins`; E2E `checkin.spec.ts::second_checkin_rejected` | 4, 8 |
| B7b | The organizer's arrived counter updates live | `test_live.py::test_two_clients_receive_registration_cancellation_and_checkin` (check-in → `checked_in` on 2 organizer streams on 2 processes), `::test_update_reaches_every_worker_of_a_multi_worker_server`, `::test_broker_routes_signals_by_event_id`; smoke SSE probe through nginx; `useEventStream.test.ts::applies_snapshots_and_reconnects` (phase 7); E2E `two_tabs.spec.ts::checkin_in_tab_b_updates_organizer_counter_in_tab_a_live` (phase 8) | 5, 7, 8 |
| B8 | If the organizer reschedules, every participant gets an email | `test_reschedule.py::test_reschedule_emails_confirmed_and_waitlisted_not_cancelled`, `::test_reschedule_email_arrives_in_mailpit`; E2E `reschedule.spec.ts::reschedule_emails_every_participant` | 6, 8 |

## Edge cases (ARCHITECTURE §6) → tests

| Edge | Test |
|---|---|
| E1 duplicate | see B2 |
| E2 re-register after cancel | `test_registration.py::test_reregister_after_cancel_creates_new_row_back_of_queue` |
| E3 email variants | `test_registration.py::test_duplicate_email_case_and_whitespace_variants`, `test_normalize.py::test_email_normalized_trim_lower` |
| E4 past event | `test_registration.py::test_register_past_event_rejected` |
| E5 cancelled event | `test_registration.py::test_register_cancelled_event_rejected`, `test_cancel.py::test_cancel_on_cancelled_event_rejected`, `test_capacity.py::test_update_cancelled_event_rejected`, `test_event_cancel.py::test_cancel_event_notifies_and_blocks_actions` |
| E1 concurrent duplicate | `test_concurrency.py::test_concurrent_same_email_creates_one_row` |
| E6 capacity below taken | `test_capacity.py::test_decrease_below_taken_rejected`, `::test_decrease_to_taken_allowed` |
| E7 capacity increase promotes | `test_capacity.py::test_increase_capacity_promotes_fifo` |
| E8 cancel after check-in | `test_cancel.py::test_cancel_after_checkin_rejected` (state set via SQL); `test_checkin.py::test_cancel_after_checkin_rejected` (via API), `::test_checkin_vs_cancel_race_exactly_one_wins` |
| E9 cancel twice | `test_cancel.py::test_cancel_is_idempotent` |
| E10 cancel after start | `test_cancel.py::test_cancel_after_event_start_rejected`; `test_capacity.py::test_capacity_change_after_start_rejected` |
| E11 event cancelled | `test_event_cancel.py::*` |
| E12 promotion email fails | `test_outbox.py::test_failed_promotion_email_keeps_seat`, `::test_dispatch_marks_failed_after_max_attempts` |
| E13 Mailpit down | `test_email_delivery.py::test_smtp_failure_retries_then_sends_once` (real connection failures, exponential backoff, exactly 1 delivery); manual outage demo on the compose stack (DEVLOG phase 3) |
| E14/E15/E16 reschedule variants | `test_reschedule.py::test_reschedule_to_past_rejected`, `::test_reschedule_same_time_is_noop`, `::test_reschedule_after_reminder_sent_sends_one_new_reminder` |
| E17 seat inside 24h window | `test_reminders.py::test_promoted_inside_window_gets_reminder_next_tick` |
| E18 downtime | `test_reminders.py::test_late_reminder_after_downtime_if_event_not_started`, `::test_no_reminder_after_event_started` |
| E19/E20/E21 check-in variants | `test_checkin.py::test_checkin_other_event_code_404`, `::test_checkin_waitlisted_ticket_rejected`, `::test_checkin_cancelled_ticket_rejected`, `::test_checkin_normalizes_input`, `::test_checkin_wrong_code_404`, `::test_checkin_malformed_code_422`, `::test_checkin_cancelled_event_rejected` |
| E22 code collision | `test_codes.py::test_code_collision_retries` |
| E23/E24 SSE reconnect | `test_live.py::test_public_stream_sends_snapshot_on_connect`, `::test_reconnect_gets_current_snapshot`, `::test_listener_connection_loss_is_healed_and_resynced`, `::test_stream_releases_subscription_when_client_goes_away`; `useEventStream.test.ts::applies_snapshots_and_reconnects` |
| Email: exactly-once enqueue, at-least-once delivery (D-043) | `test_email_delivery.py::test_worker_restart_mid_batch_does_not_duplicate`, `::test_known_window_crash_after_smtp_accept_resends_same_message_id`; `test_worker_process.py::test_sigterm_mid_batch_then_restart_sends_each_email_once`, `::test_sigkill_mid_batch_then_restart_delivers_all_at_most_one_duplicate`; `test_outbox.py::test_stale_claim_cannot_overwrite_newer_claim`, `::test_concurrent_claims_are_disjoint`, `::test_graceful_stop_releases_unsent_rows`, `::test_dispatch_marks_failed_after_max_attempts` |
| Security | `test_registration.py::test_response_never_contains_ticket_or_token`, `test_admin_auth.py::*` (401 envelope, cookie flags, tampering, logout), `test_stats.py::test_stats_requires_admin` |

## Known untestable or partially testable items (honest)

- **Exactly-once SMTP delivery** isn't guaranteed. The design is at-least-once (D-007, D-043). Tests prove exactly-once *enqueue*, disjoint claims, fencing, no duplicates on graceful restart or on a crash before send. They also **demonstrate** the one duplicate window (crash after SMTP accept, before commit: same Message-ID) and bound it to ≤1 message for a real SIGKILL.
- **Real 24h wall-clock passage** isn't tested. Time is injected in unit tests, and E2E uses an event 23h ahead.
- **Real network partitions** between API workers and Postgres are only simulated (the broker reconnect test kills the listener connection).
