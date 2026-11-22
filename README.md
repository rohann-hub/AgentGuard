# AgentGuard

A security gateway that sits between AI agents and the tools, APIs and data they use.
Every tool call is checked against policy (OPA), scanned for PII and secrets, approved by
a human when risky, and written to a tamper-evident audit log.

This repository is at **Phase 6: human approval & refund verification**. Agents are registered in PostgreSQL
and call `POST /api/v1/proxy/execute` with their API key; AgentGuard validates the request
against an explicit tool registry, scans it for PII and secrets, asks OPA for a versioned
decision (refunds are first verified against trusted payments data), records it in a
hash-chained audit ledger, runs the tool only when allowed or approved by a human, and scans
the response before returning it.

**Guides for each phase are in [docs/](docs/README.md).**

## Layout

```text
backend/app/
  main.py               FastAPI app factory
  api/dependencies.py   shared dependencies
  api/routes/health.py  /health and /health/ready
  api/routes/proxy.py   POST /api/v1/proxy/execute
  api/routes/agents.py  admin APIs: register, list, get, revoke agents
  api/routes/audit.py   admin APIs: list audit events, verify the hash chain
  api/routes/approvals.py  admin APIs: list, approve, reject approvals
  audit/ledger.py       append-only, hash-chained audit ledger
  approvals/service.py  approvals bound to the exact request, single use, expiring
  verification/         facts from trusted systems for policy (refunds)
  auth/api_keys.py      agent and admin API keys (stored as SHA-256 hashes)
  firewall/             PII and secret detectors, redact/block scanner
  policy/opa_client.py  OPA decisions; any failure denies (fail closed)
  tools/registry.py     the only tools that can run, keyed by (tool_name, action)
  tools/mock_tools.py   mock customer database and payment tools
  tools/mock_payments.py  mock payments system (trusted refund data)
  schemas/              request and response bodies
  core/config.py        settings from AGENTGUARD_* env vars and .env
  core/logging.py
  database/connection.py  async SQLAlchemy engine and sessions
  database/models.py    tables
  database/migrations/  Alembic migrations (run from backend/: alembic upgrade head)
backend/tests/
  unit/                 fast tests, no services needed
  integration/          run against the Compose stack
config/policies/        Rego policies loaded by OPA (deny by default, deny wins)
```

## Run with Docker

```bash
cp .env.example .env      # then set POSTGRES_PASSWORD and AGENTGUARD_ADMIN_API_KEY_HASH
docker compose up -d --build --wait
curl localhost:8000/health/ready
```

API docs are at http://localhost:8000/docs (hidden when `AGENTGUARD_ENV=production`).
OPA (8181) and PostgreSQL (5432) are bound to 127.0.0.1 only.

## Run locally

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cd backend && alembic upgrade head && uvicorn app.main:app --reload
```

To use your own PostgreSQL, set `AGENTGUARD_DATABASE_URL`; see [docs/phase-3.md](docs/phase-3.md).

## Tests

```bash
pytest                    # unit tests
pytest -m integration     # needs `docker compose up` first
opa test config/policies backend/tests/policies   # policy tests
ruff check . && ruff format --check .
```

## Health endpoints

| Endpoint | Meaning |
|---|---|
| `GET /health` | The process is up. Does not touch dependencies. |
| `GET /health/ready` | PostgreSQL and OPA both answer. Returns 503 otherwise, so traffic fails closed. |

## Quick tour

```bash
# register an agent (admin key), then call a tool with the agent's key
curl -s localhost:8000/api/v1/agents -H "X-Admin-Key: $ADMIN_KEY" \
  -H 'content-type: application/json' -d '{"name":"support-agent"}'
curl -s localhost:8000/api/v1/proxy/execute -H "X-API-Key: $AGENT_KEY" -H 'content-type: application/json' \
  -d '{"tool_name":"database","action":"read","arguments":{"customer_id":101}}'
```

Read is allowed, delete is denied, refunds are verified and follow amount tiers, and if OPA or the database is
down nothing runs. Secrets in arguments or responses block the call; PII is redacted.
Details: [docs/](docs/README.md).
