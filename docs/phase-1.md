# Phase 1: Project foundation

## What was built

- FastAPI app factory (`backend/app/main.py`) with API docs hidden when `AGENTGUARD_ENV=production`.
- Settings from `AGENTGUARD_*` environment variables and `.env` (`backend/app/core/config.py`).
- Async SQLAlchemy engine for PostgreSQL, created lazily (`backend/app/database/connection.py`).
- Health endpoints (`backend/app/api/routes/health.py`):
  - `GET /health`: the process is up. Never touches dependencies.
  - `GET /health/ready`: PostgreSQL and OPA both answer, otherwise 503, so traffic fails closed.
- Docker Compose stack: backend, PostgreSQL 16, OPA 1.4. OPA and Postgres bind to 127.0.0.1 only.
- CI (`.github/workflows/tests.yml`): ruff lint and format, unit tests, then integration tests
  against the real Compose stack.

## How to use it

```bash
cp .env.example .env                 # set POSTGRES_PASSWORD
docker compose up -d --build --wait
curl localhost:8000/health/ready     # {"status":"ready","checks":{"database":"ok","opa":"ok"}}
```

To use a PostgreSQL that is already on your machine instead of the Compose one, see
"Run without Docker" in [phase-3.md](phase-3.md).

## Tests

```bash
pip install -r requirements-dev.txt
pytest                    # unit tests, no services needed
pytest -m integration     # against the running Compose stack
ruff check . && ruff format --check .
```
