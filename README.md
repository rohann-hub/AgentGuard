# AgentGuard

A security gateway that sits between AI agents and the tools, APIs and data they use.
Every tool call is checked against policy (OPA), scanned for PII and secrets, approved by
a human when risky, and written to a tamper-evident audit log.

This repository is at **Phase 1: project foundation**. It contains the FastAPI app,
settings, health checks, tests, the Docker Compose stack and CI. The proxy, policy,
firewall, approval and audit modules arrive in later phases.

## Layout

```text
backend/app/
  main.py               FastAPI app factory
  api/dependencies.py   shared dependencies
  api/routes/health.py  /health and /health/ready
  core/config.py        settings from AGENTGUARD_* env vars and .env
  core/logging.py
  database/connection.py  async SQLAlchemy engine
backend/tests/
  unit/                 fast tests, no services needed
  integration/          run against the Compose stack
config/policies/        Rego policies loaded by OPA (deny by default)
```

## Run with Docker

```bash
cp .env.example .env      # then set POSTGRES_PASSWORD
docker compose up -d --build --wait
curl localhost:8000/health/ready
```

API docs are at http://localhost:8000/docs (hidden when `AGENTGUARD_ENV=production`).
OPA (8181) and PostgreSQL (5432) are bound to 127.0.0.1 only.

## Run locally

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cd backend && uvicorn app.main:app --reload
```

## Tests

```bash
pytest                    # unit tests
pytest -m integration     # needs `docker compose up` first
ruff check . && ruff format --check .
```

## Health endpoints

| Endpoint | Meaning |
|---|---|
| `GET /health` | The process is up. Does not touch dependencies. |
| `GET /health/ready` | PostgreSQL and OPA both answer. Returns 503 otherwise, so traffic fails closed. |
