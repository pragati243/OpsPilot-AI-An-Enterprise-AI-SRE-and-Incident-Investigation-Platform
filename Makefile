.PHONY: up down logs sync dev mcp-dev migrate revision seed-demo test evals lint typecheck

up: ## Start Postgres + Redis for local dev
	docker compose up -d postgres redis

down: ## Stop all local infra containers
	docker compose down

logs: ## Tail infra container logs
	docker compose logs -f

sync: ## Install/sync Python dependencies into .venv
	uv sync --all-groups

# Port 8010, not 8000: this dev machine already runs another project's
# backend container on 8000.
dev: ## Run the FastAPI app with autoreload
	uv run uvicorn app.main:app --reload --app-dir apps/api --port 8010

# Port 8020: 8000/8010 (API) and 5173/5180 (dashboard) are already taken
# on this dev machine, same reasoning as apps/api's own port move.
mcp-dev: ## Run the MCP server (Streamable HTTP) for local dev
	uv run python apps/mcp-server/server.py

migrate: ## Apply Alembic migrations
	cd apps/api && uv run --project .. alembic upgrade head

revision: ## Autogenerate a new Alembic migration; usage: make revision m="add x"
	cd apps/api && uv run --project .. alembic revision --autogenerate -m "$(m)"

seed-demo: ## Seed one demo tenant with services, runbooks, and incidents
	uv run python infra/scripts/seed_demo_data.py

test: ## Run the backend test suite against the ephemeral test Postgres
	docker compose --profile test up -d postgres-test redis
	uv run pytest

evals: ## Run the golden evaluation dataset (CI quality gate) — needs DATABASE_URL reachable
	uv run python evals/run_evals.py

lint: ## Ruff lint
	uv run ruff check .

typecheck: ## mypy
	uv run mypy apps/api/app apps/mcp-server evals
