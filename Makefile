# Nirikshan - common developer tasks.
# `make help` lists targets.  Python venv assumed at .venv (see `make venv`).

PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python.exe
endif

TEST_DB ?= postgresql+psycopg://nirikshan:nirikshan@localhost:5433/nirikshan
TEST_REDIS ?= redis://localhost:6380/15

.DEFAULT_GOAL := help
.PHONY: help venv install lint typecheck test test-int eval loadtest \
        migrate up down logs seed scenario web-install web-build web-e2e fmt

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create the Python virtualenv
	python -m venv .venv

install: ## Install the package + dev extras
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

lint: ## Ruff
	$(PY) -m ruff check src tests evaluation scripts

typecheck: ## mypy (advisory)
	$(PY) -m mypy src || true

test: ## Unit / e2e / failure / ai_eval (SQLite + fakeredis)
	$(PY) -m pytest -q -m "not integration"

test-int: ## Integration tests (needs `make up` datastores)
	NIRIKSHAN_TEST_DATABASE_URL=$(TEST_DB) NIRIKSHAN_TEST_REDIS_URL=$(TEST_REDIS) \
	  $(PY) -m pytest -q -m integration

eval: ## AI evaluation harness (CI gate)
	$(PY) evaluation/run_eval.py

loadtest: ## Telemetry ingestion load test (needs the API running)
	$(PY) scripts/loadtest.py --url http://localhost:8000

migrate: ## alembic upgrade head
	$(PY) -m alembic upgrade head

up: ## docker compose up (postgres, redis, api, worker, web) + one-shot seed
	docker compose up -d --build

down: ## docker compose down (add ARGS=-v to drop volumes)
	docker compose down $(ARGS)

logs: ## Tail compose logs
	docker compose logs -f --tail=100

seed: ## Seed the demo environment (CLI)
	$(PY) -m nirikshan.demo seed

scenario: ## Run a scenario end-to-end, e.g. `make scenario KEY=db-exhaustion`
	$(PY) -m nirikshan.demo scenario $(KEY) --remediate

web-install: ## npm install for the dashboard
	cd apps/web && npm ci || (cd apps/web && npm install)

web-build: ## Build the Next.js dashboard
	cd apps/web && npm run build

web-e2e: ## Playwright E2E (needs `make up` + a seeded incident)
	cd apps/web && npx playwright test
