# AgentGuard

A security gateway that sits between AI agents and the tools, APIs and data they use.
Every tool call is checked against policy (OPA), scanned for PII and secrets, approved by
a human when risky, and written to a tamper-evident audit log.

This repository is at **Phase 2: tool gateway**. Agents call `POST /api/v1/proxy/execute`
with their API key; AgentGuard validates the request against an explicit tool registry,
asks OPA for a decision, and runs the tool only when OPA allows it. The firewall,
approval workflow and audit ledger arrive in later phases.

## Layout

```text
backend/app/
  main.py               FastAPI app factory
  api/dependencies.py   shared dependencies
  api/routes/health.py  /health and /health/ready
  api/routes/proxy.py   POST /api/v1/proxy/execute
  auth/api_keys.py      one API key per agent (stored as SHA-256 hashes)
  policy/opa_client.py  OPA decisions; any failure denies (fail closed)
  tools/registry.py     the only tools that can run, keyed by (tool_name, action)
  tools/mock_tools.py   mock customer database and payment tools
  schemas/proxy.py      request and response bodies
  core/config.py        settings from AGENTGUARD_* env vars and .env
  core/logging.py
  database/connection.py  async SQLAlchemy engine
backend/tests/
  unit/                 fast tests, no services needed
  integration/          run against the Compose stack
config/policies/        Rego policies loaded by OPA (deny by default, deny wins)
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

## Tool gateway

Register an agent by putting the SHA-256 hash of its key in `.env` (the raw key is never stored):

```bash
python -c "import secrets,hashlib;k=secrets.token_urlsafe(32);print(k, hashlib.sha256(k.encode()).hexdigest())"
# .env:  AGENTGUARD_AGENT_API_KEYS={"support-agent":"<hash>"}
```

Then call the proxy with the raw key:

```bash
curl -s localhost:8000/api/v1/proxy/execute -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"tool_name":"database","action":"read","arguments":{"customer_id":101}}'
```

| Tool call | Policy | HTTP | Tool runs? |
|---|---|---|---|
| `database.read` | allow | 200 `success` | yes |
| `database.delete` | deny | 403 `blocked` | no |
| `payment.refund` | approval required | 202 `pending_approval` | no |
| anything else | not in registry | 404 | no |
| OPA down or invalid answer | deny | 503 `blocked` | no |

Missing or wrong API key returns 401. Invalid arguments return 422 before OPA is asked.
The agent's identity always comes from its key; the body cannot set it.
