#!/usr/bin/env bash
# `make proof`: run every check this project has, then print a pass/fail table mapped to
# docs/TEST_PLAN.md (scripts/proof_report.py). Keeps going after a failing step so the table
# shows everything; exits non-zero if anything failed or a documented test was not found.
#   PROOF_LOOP=N   concurrency-loop repetitions (default 5; the phase-2 evidence used 20)
set -uo pipefail
cd "$(dirname "$0")/.."

mkdir -p reports && chmod 777 reports
rm -f reports/*.xml reports/*.json reports/steps.txt

step() {  # step <name> <command...>
  local name=$1; shift
  local start=$SECONDS
  echo; echo "================ $name"
  if "$@"; then echo "$name=pass" >> reports/steps.txt; r=PASS; else echo "$name=fail" >> reports/steps.txt; r=FAIL; fi
  echo "---------------- $name: $r ($((SECONDS - start))s)"
}

TEST="docker compose --profile test run --rm --build"
step lint make lint
step backend $TEST backend-test pytest -q -p no:warnings --junitxml=/reports/backend.xml
step frontend $TEST frontend-test npx vitest run --reporter=default --reporter=junit --outputFile.junit=/reports/frontend.xml
step concurrency_loop make test-concurrency-loop N="${PROOF_LOOP:-5}"
step smoke ./scripts/smoke_compose.sh
echo; echo "================ e2e + stress (isolated stack)"
E2E_WITH_STRESS=1 ./scripts/e2e.sh  # records e2e=… and stress=… itself

echo; echo "================ report"
docker compose --profile test run --rm --no-deps backend-test \
  python /scripts/proof_report.py --plan /docs/TEST_PLAN.md --reports /reports
