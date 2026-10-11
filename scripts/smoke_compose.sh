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

echo "SMOKE PASS: $passed checks"
