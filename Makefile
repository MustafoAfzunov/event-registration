# Thin wrapper around docker compose so every command runs the same way on every machine.
SHELL := /bin/bash
COMPOSE ?= docker compose
TEST := $(COMPOSE) --profile test run --rm --build

.DEFAULT_GOAL := help
.PHONY: help up down clean logs ps migrate test test-backend test-frontend test-smoke test-all \
        lint lint-backend lint-frontend

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

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

test-frontend: ## Frontend tests (vitest)
	$(TEST) frontend-test npm test

test-smoke: ## Boot a throwaway stack from scratch with `make up` and probe it
	./scripts/smoke_compose.sh

test-all: test test-smoke ## Everything

lint: lint-backend lint-frontend ## All linters and type checks

lint-backend: .env ## ruff + mypy --strict
	$(TEST) backend-test sh -c "ruff check . && ruff format --check . && mypy"

lint-frontend: ## eslint + tsc
	$(TEST) frontend-test sh -c "npm run lint && npm run typecheck"
