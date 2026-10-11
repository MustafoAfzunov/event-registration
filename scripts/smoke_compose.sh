#!/usr/bin/env bash
# Proves the stack boots from scratch with `make up`:
#   - a throwaway compose project (own containers, network, volumes) so your dev stack and its
#     data are never touched;
#   - non-default host ports so it can run next to the dev stack;
#   - fresh DB volume => migrations and the test-DB init script run from zero.
# Docker's build cache IS reused unless SMOKE_NO_CACHE=1 (then images are rebuilt with --no-cache).
# Everything (containers, volumes, project images) is removed on exit, pass or fail.
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME="eventreg-smoke-$$"
export FRONTEND_PORT=18080 BACKEND_PORT=18000 DB_PORT=15433 MAILPIT_UI_PORT=18025 MAILPIT_SMTP_PORT=11025
PGUSER="${POSTGRES_USER:-eventreg}" PGDB="${POSTGRES_DB:-eventreg}"

cleanup() { docker compose down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true; }
trap cleanup EXIT

passed=0
fail() {
  echo "SMOKE FAIL: $*" >&2
  docker compose ps -a >&2 || true
  docker compose logs --tail=40 >&2 || true
  exit 1
}
ok() { echo "  ok  $*"; passed=$((passed + 1)); }

if [[ "${SMOKE_NO_CACHE:-0}" == "1" ]]; then
  docker compose build --no-cache
fi

echo "== make up (project $COMPOSE_PROJECT_NAME)"
start=$(date +%s)
make up || fail "make up did not bring the stack to healthy"
echo "== stack healthy after $(( $(date +%s) - start ))s; probing"

body=$(curl -fsS "http://localhost:$BACKEND_PORT/health") || fail "backend /health unreachable"
[[ "$body" == '{"status":"ok","db":"ok"}' ]] || fail "backend /health body: $body"
ok "backend :$BACKEND_PORT/health -> $body"

body=$(curl -fsS "http://localhost:$FRONTEND_PORT/api/health") || fail "frontend proxy /api/health"
[[ "$body" == '{"status":"ok","db":"ok"}' ]] || fail "proxied /api/health body: $body"
ok "frontend :$FRONTEND_PORT/api/health (nginx -> backend over compose network) -> $body"

curl -fsS "http://localhost:$FRONTEND_PORT/" | grep -q '<div id="root">' || fail "frontend index.html"
ok "frontend :$FRONTEND_PORT/ serves the React app"

curl -fsS "http://localhost:$MAILPIT_UI_PORT/api/v1/info" >/dev/null || fail "mailpit API"
ok "mailpit :$MAILPIT_UI_PORT/api/v1/info responds"

code=$(docker compose ps -a migrate --format '{{.ExitCode}}')
[[ "$code" == "0" ]] || fail "migrate exit code $code"
ok "migrate service exited 0"

head=$(docker compose run --rm --no-deps -T migrate alembic heads | awk '{print $1}')
current=$(docker compose exec -T db psql -U "$PGUSER" -d "$PGDB" -tAc "SELECT version_num FROM alembic_version")
[[ -n "$head" && "$current" == "$head" ]] || fail "db at revision '$current', head is '$head'"
ok "database at alembic head ($current)"

docker compose exec -T db psql -U "$PGUSER" -d "$PGDB" -tAc \
  "SELECT 1 FROM pg_database WHERE datname = '${PGDB}_test'" | grep -q 1 || fail "test DB missing"
ok "test database ${PGDB}_test was created by the init script"

# Registration path through nginx on the real 2-worker deployment (organizer cookie + API).
jar=$(mktemp); trap 'rm -f "$jar"; cleanup' EXIT
api="http://localhost:$FRONTEND_PORT/api"
pw="${ORGANIZER_PASSWORD:-organizer-dev-password}"
[[ -f .env ]] && pw=$(grep -E '^ORGANIZER_PASSWORD=' .env | cut -d= -f2- || echo "$pw")
code=$(curl -s -o /dev/null -w '%{http_code}' -c "$jar" -H 'Content-Type: application/json' \
  -d "{\"password\":\"$pw\"}" "$api/admin/login")
[[ "$code" == "204" ]] || fail "organizer login returned $code"
starts=$(date -u -d '+7 days' +%Y-%m-%dT%H:%M:%SZ)
event=$(curl -fsS -b "$jar" -H 'Content-Type: application/json' \
  -d "{\"title\":\"Smoke\",\"starts_at\":\"$starts\",\"capacity\":1}" "$api/admin/events") \
  || fail "create event"
event_id=$(echo "$event" | sed -E 's/.*"id":"([^"]+)".*/\1/')
# example.com: email-validator rejects special-use domains such as .test/.local.
r1=$(curl -sS -H 'Content-Type: application/json' -d '{"email":"One@Example.com"}' "$api/events/$event_id/registrations")
r2=$(curl -sS -H 'Content-Type: application/json' -d '{"email":"two@example.com"}' "$api/events/$event_id/registrations")
[[ "$r1" == *'"status":"confirmed"'* && "$r2" == *'"status":"waitlisted"'* ]] \
  || fail "registration flow: $r1 / $r2"
ok "organizer login + create event + register (confirmed, then waitlisted) via nginx"

# The worker container delivers both emails (ticket + waitlist notice) to Mailpit.
mp="http://localhost:$MAILPIT_UI_PORT/api/v1/messages"
for _ in $(seq 1 30); do
  n=$(curl -fsS "$mp" | grep -o '"Subject":"[^"]*"' | grep -c 'Smoke' || true)
  [[ "$n" -ge 2 ]] && break; sleep 0.5
done
subjects=$(curl -fsS "$mp" | grep -o '"Subject":"[^"]*"')
[[ "$subjects" == *'Your ticket for Smoke'* && "$subjects" == *'waitlist for Smoke'* ]] \
  || fail "emails not delivered by worker: $subjects"
[[ "$(echo "$subjects" | grep -c Smoke)" == "2" ]] || fail "expected exactly 2 emails: $subjects"
ok "worker delivered exactly 2 emails (ticket + waitlist notice) to Mailpit"

# Door flow: ticket code from the real email -> check-in via nginx -> second scan rejected -> stats.
ticket_id=$(curl -fsS -G "http://localhost:$MAILPIT_UI_PORT/api/v1/search" \
  --data-urlencode 'query=to:"One@Example.com" subject:"Your ticket"' | grep -o '"ID":"[^"]*"' | head -1 | cut -d'"' -f4)
[[ -n "$ticket_id" ]] || fail "ticket email for One@Example.com not found via Mailpit search"
code=$(curl -fsS "http://localhost:$MAILPIT_UI_PORT/api/v1/message/$ticket_id" \
  | grep -oE 'Your ticket code: [0-9A-Z]{4}-[0-9A-Z]{4}' | awk '{print $4}')
[[ -n "$code" ]] || fail "could not read ticket code from the email"
c1=$(curl -s -o /dev/null -w '%{http_code}' -b "$jar" -H 'Content-Type: application/json' \
  -d "{\"code\":\"$code\"}" "$api/admin/events/$event_id/checkin")
c2=$(curl -s -b "$jar" -H 'Content-Type: application/json' -d "{\"code\":\"$code\"}" "$api/admin/events/$event_id/checkin")
stats=$(curl -fsS -b "$jar" "$api/admin/events/$event_id/stats")
[[ "$c1" == "200" && "$c2" == *'"already_checked_in"'* && "$stats" == *'"checked_in":1'* && "$stats" == *'"waitlisted":1'* ]] \
  || fail "check-in flow: first=$c1 second=$c2 stats=$stats"
ok "check-in with code from the email: 200, second scan 409 already_checked_in, stats checked_in=1"

echo "SMOKE PASS: $passed checks"
