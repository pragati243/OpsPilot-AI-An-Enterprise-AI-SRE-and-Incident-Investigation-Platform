.PHONY: up down logs sync dev migrate revision test lint typecheck

up: ## Start Postgres + Redis for local dev
	docker compose up -d postgres redis

down: ## Stop all local infra containers
	docker compose down

logs: ## Tail infra container logs
	docker compose logs -f

sync: ## Install/sync Python dependencies into .venv
	uv sync --all-groups

dev: ## Run the FastAPI app with autoreload
	uv run uvicorn app.main:app --reload --app-dir apps/api --port 8000

migrate: ## Apply Alembic migrations
	cd apps/api && uv run --project .. alembic upgrade head

revision: ## Autogenerate a new Alembic migration; usage: make revision m="add x"
	cd apps/api && uv run --project .. alembic revision --autogenerate -m "$(m)"

test: ## Run the backend test suite against the ephemeral test Postgres
	docker compose --profile test up -d postgres-test redis
	uv run pytest

lint: ## Ruff lint
	uv run ruff check .

typecheck: ## mypy
	uv run mypy apps/api/app
