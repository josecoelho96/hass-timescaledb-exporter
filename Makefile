.PHONY: help install lint format test test-unit test-integration test-all \
       e2e-up e2e-down e2e-logs e2e-psql clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────────────

install: ## Create venv and install dev dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip setuptools wheel
	$(VENV)/bin/pip install -e ".[dev]"

# ── Quality ──────────────────────────────────────────────────────────────────

lint: ## Run ruff linter
	$(RUFF) check custom_components/ tests/

format: ## Auto-format code with ruff
	$(RUFF) format custom_components/ tests/

format-check: ## Check formatting without modifying files
	$(RUFF) format --check custom_components/ tests/

check: lint format-check ## Run all quality checks (lint + format)

# ── Tests ────────────────────────────────────────────────────────────────────

test: test-unit ## Alias for test-unit

test-unit: ## Run unit tests
	$(PYTEST) tests/ -m "not integration" -vv --no-cov

test-integration: ## Run integration tests (requires TimescaleDB container)
	docker compose up timescaledb -d --wait
	$(PYTEST) tests/ -m integration -vv --no-cov

test-all: ## Run all tests (unit + integration)
	docker compose up timescaledb -d --wait
	$(PYTEST) tests/ -vv --no-cov

# ── E2E / Manual Testing ────────────────────────────────────────────────────

e2e-up: ## Start full HA + TimescaleDB stack for manual testing
	@mkdir -p ha-config
	docker compose up -d
	@echo ""
	@echo "  Home Assistant: http://localhost:8123"
	@echo "  TimescaleDB:    postgresql://postgres:postgres@localhost:5432/homeassistant"
	@echo ""
	@echo "  Complete HA onboarding, then add the 'TimescaleDB Exporter' integration."
	@echo "  Use host=timescaledb, port=5432, database=homeassistant,"
	@echo "  username=postgres, password=postgres, SSL=off"

e2e-down: ## Stop the full stack
	docker compose down

e2e-logs: ## Tail logs from all containers
	docker compose logs -f

e2e-psql: ## Open psql shell to TimescaleDB
	docker exec -it timescaledb psql -U postgres -d homeassistant

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Remove everything including venv and docker volumes
	rm -rf $(VENV)
	docker compose down -v 2>/dev/null || true
