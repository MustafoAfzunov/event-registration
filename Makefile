# Thin wrapper around docker compose so every command runs the same way on every machine.
SHELL := /bin/bash
COMPOSE ?= docker compose
TEST := $(COMPOSE) --profile test run --rm --build

.DEFAULT_GOAL := help
.PHONY: help up down clean logs ps migrate test test-backend test-frontend test-smoke test-all \
        test-concurrency-loop e2e stress proof \
        lint lint-backend lint-frontend

help: ## List targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

up: .env ## Build and start the whole stack; returns once every service is healthy
	$(COMPOSE) up --build --detach --wait
	@echo; \
	  echo "App:      http://$$($(COMPOSE) port frontend 80 | sed s/0.0.0.0/localhost/)"; \
	  echo "API:      http://$$($(COMPOSE) port backend 8000 | sed s/0.0.0.0/localhost/)/api/health  (OpenAPI: /docs)"; \
	  echo "Mailpit:  http://$$($(COMPOSE) port mailpit 8025 | sed s/0.0.0.0/localhost/)"

down: ## Stop the stack (keeps the database volume)
	$(COMPOSE) down

clean: ## Stop the stack and DELETE the database volume
	$(COMPOSE) down --volumes --remove-orphans

logs: ## Follow logs of all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps -a

migrate: .env ## Apply database migrations (alembic upgrade head)
	$(COMPOSE) run --rm --build migrate

test: test-backend test-frontend ## Backend + frontend tests

test-backend: .env ## Backend tests (pytest, real Postgres test DB)
	$(TEST) backend-test pytest -v

N ?= 20
test-concurrency-loop: .env ## Run the concurrency tests N times (default 20) as separate pytest processes
	$(TEST) backend-test sh -c 'pass=0; fail=0; \
	  for i in $$(seq 1 $(N)); do \
	    if out=$$(pytest -q tests/test_concurrency.py 2>&1); then \
	      pass=$$((pass + 1)); echo "run $$i/$(N): PASS  $$(echo "$$out" | tail -1)"; \
	    else \
	      fail=$$((fail + 1)); echo "run $$i/$(N): FAIL"; echo "$$out" | tail -40; \
	    fi; \
	  done; \
	  echo "== $$pass passed, $$fail failed out of $(N) runs"; [ $$fail -eq 0 ]'

test-frontend: ## Frontend tests (vitest)
	$(TEST) frontend-test npm test

test-smoke: ## Boot a throwaway stack from scratch with `make up` and probe it
	./scripts/smoke_compose.sh

test-all: test test-smoke ## Everything

e2e: ## Browser E2E (Playwright, 2 contexts) against an isolated throwaway stack
	./scripts/e2e.sh

stress: .env ## 200+ concurrent registrations + mixed cancels against the RUNNING dev stack (make up first)
	$(TEST) --no-deps backend-test python /scripts/stress.py --base http://frontend --mailpit http://mailpit:8025

proof: ## Run EVERYTHING and print a pass/fail table mapped to docs/TEST_PLAN.md
	./scripts/proof.sh

lint: lint-backend lint-frontend ## All linters and type checks

lint-backend: .env ## ruff + mypy --strict
	$(TEST) backend-test sh -c "ruff check . && ruff format --check . && mypy"

lint-frontend: ## eslint + tsc
	$(TEST) frontend-test sh -c "npm run lint && npm run typecheck"
