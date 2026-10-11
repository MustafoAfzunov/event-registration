#!/usr/bin/env bash
# Browser E2E (Playwright, two browser contexts = two tabs) against an ISOLATED stack:
# own compose project, ports, volumes; worker scheduler ticks every 2s so the reminder test
# doesn't wait 30s. Your dev stack and its data are never touched.
#   E2E_WITH_STRESS=1  also run scripts/stress.py against the same stack (2 uvicorn workers)
#   E2E_KEEP=1         leave the stack running afterwards (for debugging)
# Writes reports/e2e.xml (JUnit), reports/stress.json, reports/steps.txt lines.
set -uo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME="eventreg-e2e"
export FRONTEND_PORT=28080 BACKEND_PORT=28000 DB_PORT=25433 MAILPIT_UI_PORT=28025 MAILPIT_SMTP_PORT=21025
export SCHEDULER_TICK_SECONDS=2

cleanup() {
  [[ "${E2E_KEEP:-0}" == "1" ]] && { echo "stack left running (project $COMPOSE_PROJECT_NAME)"; return; }
  docker compose --profile e2e --profile test down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p reports && chmod 777 reports
docker compose --profile e2e --profile test down --volumes --remove-orphans >/dev/null 2>&1 || true

echo "== starting isolated stack ($COMPOSE_PROJECT_NAME)"
make up >/dev/null || { echo "E2E: stack did not become healthy"; echo "e2e=fail" >> reports/steps.txt; exit 1; }

status=0
echo "== Playwright"
if docker compose --profile e2e run --rm --build e2e; then
  echo "e2e=pass" >> reports/steps.txt
else
  echo "e2e=fail" >> reports/steps.txt; status=1
fi

if [[ "${E2E_WITH_STRESS:-0}" == "1" ]]; then
  echo "== stress (through nginx -> 2 uvicorn workers)"
  if docker compose --profile test run --rm --build --no-deps backend-test \
       python /scripts/stress.py --base http://frontend --mailpit http://mailpit:8025 \
       --report /reports/stress.json; then
    echo "stress=pass" >> reports/steps.txt
  else
    echo "stress=fail" >> reports/steps.txt; status=1
  fi
fi
exit $status
