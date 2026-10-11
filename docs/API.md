# API Contract

Base path: `/api`. JSON in and out (`Content-Type: application/json`). Times are ISO-8601 with offset, and the server always returns UTC (`Z`). Status: **contract only (phase 0)**. The phases that implement each group are noted.

## Conventions

**Error envelope** (every non-2xx response):
```json
{ "error": { "code": "registration_closed", "message": "Registration closed: the event has started.", "details": {} } }
```
`code` is stable and machine-readable. Tests and the frontend switch on `code`, never on `message`.

Generic codes: `validation_error` (422, `details.fields`), `not_found` (404), `unauthorized` (401), `internal_error` (500, no stack trace in the body).

**Auth.**
- *Organizer:* `POST /api/admin/login` sets cookie `eventreg_admin` (signed, httpOnly, `SameSite=Strict`, `Path=/api`, 12h). Every `/api/admin/*` endpoint except `login` needs it, and returns `401 unauthorized` without it.
- *Participant:* the `manage_token` path segment from the emailed link is the credential.

**Public views never include PII** (no emails) except to the token holder.

---

## Health — phase 1

### `GET /api/health` (alias: `GET /health`)
`200 {"status":"ok","db":"ok"}` · `503 {"status":"degraded","db":"error"}`

The DB probe (`SELECT 1`) has a 2s budget (`HEALTH_DB_TIMEOUT_SECONDS`), so the endpoint never hangs. `/health` isn't proxied by nginx (only `/api/*` is). It's used by the container healthcheck and for probing the backend directly.

---

## Public events — phase 2

### `GET /api/events`
Lists scheduled events with `starts_at > now`, ordered by `starts_at`.
```json
200 [{ "id":"uuid","title":"…","description":"…","starts_at":"2026-11-01T15:00:00Z",
       "capacity":50,"seats_left":3,"waitlist_count":0,"status":"scheduled" }]
```

### `GET /api/events/{event_id}`
`200` with the same object shape (cancelled and past events are returned too) · `404 event_not_found`

### `POST /api/events/{event_id}/registrations`
Request: `{ "email": "Alice@Example.com " }`

`201 Created` (new registration) or `200 OK` (an active registration already exists for this email):
```json
{ "created": true,
  "status": "confirmed",            // or "waitlisted"
  "waitlist_position": null,        // integer when waitlisted
  "email": "Alice@Example.com",
  "message": "You're in! Your ticket was sent to Alice@Example.com." }
```
There's no ticket code and no token in the response (ARCHITECTURE A9). Both are emailed.

| HTTP | code | when |
|---|---|---|
| 404 | `event_not_found` | |
| 409 | `event_cancelled` | event is cancelled |
| 409 | `registration_closed` | `starts_at <= now` |
| 422 | `invalid_email` | fails syntax validation, is non-ASCII, or is longer than 320 chars |
| 422 | `validation_error` | malformed body (e.g. missing `email`, unknown fields) |

---

## Participant (manage link) — phase 2 (view/cancel), phase 3 (ticket code shown)

### `GET /api/registrations/{manage_token}`
```json
200 { "event": { …public event… },
      "email": "Alice@Example.com",
      "status": "confirmed",          // confirmed | waitlisted | cancelled | checked_in
      "ticket_code": "ABCD-EFGH",     // only when confirmed or checked_in, else null
      "waitlist_position": null,
      "checked_in_at": null }
```
`404 registration_not_found`

### `POST /api/registrations/{manage_token}/cancel`
`200 { "status": "cancelled" }`. This is idempotent: cancelling an already-cancelled registration returns 200 and changes nothing.

| HTTP | code | when |
|---|---|---|
| 404 | `registration_not_found` | |
| 409 | `already_checked_in` | |
| 409 | `event_started` | `starts_at <= now` |
| 409 | `event_cancelled` | |

Side effects: if the registration was `confirmed`, the first waitlisted person is promoted in the same transaction and gets a `promoted` email. The canceller gets a `cancelled` confirmation email.

---

## Live stream — phase 5

### `GET /api/events/{event_id}/stream`
`Content-Type: text/event-stream`. Public, counts only, no PII.
```
event: stats
data: {"event_id":"…","capacity":50,"confirmed":47,"checked_in":12,"waitlisted":3,"seats_left":0,"starts_at":"…","status":"scheduled","schedule_version":2}

: keepalive
```
- The first `stats` message is sent immediately on connect (snapshot).
- After that, a message is sent whenever the counts change. Bursts are coalesced.
- `confirmed` counts seat holders who haven't checked in. `checked_in` counts arrivals. `seats_left = capacity − confirmed − checked_in`.
- `404 event_not_found` (plain JSON) if the event doesn't exist.

---

## Organizer — phases 2, 4, 6

### `POST /api/admin/login`
`{ "password": "…" }` → `204` and sets the cookie · `401 invalid_credentials`. The comparison is constant-time.

### `POST /api/admin/logout` → `204` (clears the cookie)
### `GET /api/admin/me` → `200 {"role":"organizer"}` · `401`

### `GET /api/admin/events`
All events, including past and cancelled, newest `starts_at` first. Same shape as the public list.

### `POST /api/admin/events` — phase 2
```json
{ "title":"PyCon meetup", "description":"…", "starts_at":"2026-11-01T15:00:00+06:00", "capacity":50 }
```
`201` returns the event · `422 validation_error` · `422 starts_in_past`

### `PATCH /api/admin/events/{event_id}` — phase 2
Any subset of `{ "title", "description", "capacity" }`. Unknown fields (including `starts_at`) → `422 validation_error`. **`starts_at` isn't accepted here.** Use reschedule, so the notification semantics stay explicit.

`200` returns the event and `promoted_count` (when capacity grew).

| HTTP | code | when |
|---|---|---|
| 404 | `event_not_found` | |
| 409 | `capacity_below_taken` | `details: {"seats_taken": n}` |
| 409 | `event_cancelled` | |
| 409 | `event_started` | capacity change after start |

### `POST /api/admin/events/{event_id}/reschedule` — phase 6
`{ "starts_at": "…" }` → `200 { "event": {…}, "notified": 41, "changed": true }`. Rescheduling to the same time returns `changed:false, notified:0`.

Errors: `404 event_not_found`, `409 event_cancelled`, `422 starts_in_past`.

### `POST /api/admin/events/{event_id}/cancel` — phase 6
`200 { "event": {…, "status":"cancelled"}, "notified": 44 }`. This is idempotent: cancelling again returns `notified: 0`.

### `GET /api/admin/events/{event_id}/stats` — phase 4
```json
200 { "capacity":50, "confirmed":35, "checked_in":12, "waitlisted":3, "cancelled":4, "seats_left":3,
      "emails": { "pending":0, "sent":61, "failed":1, "skipped":2 } }
```
`registered` in the brief's wording = `confirmed + checked_in`. The UI shows both numbers.

### `GET /api/admin/events/{event_id}/registrations?status=waitlisted`
`200 [{ "id","email","status","ticket_code","waitlist_position","created_at","checked_in_at" }]`. Waitlisted rows are ordered by queue position, the rest by `created_at`.

### `POST /api/admin/events/{event_id}/checkin` — phase 4
`{ "code": "abcd efgh" }`. The code is normalized: uppercase, spaces and dashes removed, O→0, I/L→1.

`200 { "result":"checked_in", "email":"Alice@Example.com", "checked_in_at":"…" }`

| HTTP | code | details |
|---|---|---|
| 404 | `ticket_not_found` | code doesn't exist for this event |
| 409 | `already_checked_in` | `{"checked_in_at": "…", "email": "…"}` |
| 409 | `ticket_not_active` | `{"status": "waitlisted" \| "cancelled"}` |
| 409 | `event_cancelled` | |
| 422 | `invalid_code_format` | not 8 Crockford chars after normalization |

---

## Status code summary
`200` OK / idempotent repeat · `201` created · `204` no content · `401` organizer auth missing or invalid · `404` unknown resource · `409` the request is valid but conflicts with current state (business rule) · `422` the input is malformed · `503` the DB is unreachable (health only).
