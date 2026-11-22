# Phase 3: Authentication & policy engine

Phase 2 already connected OPA and enforced allow/deny/approval. Phase 3 adds:

- **Agent registration in PostgreSQL**, with admin APIs to register, list, inspect and revoke agents.
- **Database-backed API key authentication** for the proxy (replaces Phase 2's env-var keys).
- **Policy versioning**: every decision carries the version of the policy that made it.

## What was built

| File | Role |
|---|---|
| `backend/app/database/models.py` | `agents` table |
| `backend/app/database/migrations/` | Alembic migrations (`0001_create_agents`) |
| `backend/alembic.ini` | Alembic config; the URL comes from `AGENTGUARD_DATABASE_URL` |
| `backend/app/api/routes/agents.py` | Admin agent APIs |
| `backend/app/auth/api_keys.py` | Agent and admin key checks |
| `config/policies/agentguard.rego` | `policy_version` added to each decision |

### agents table

| Column | Type | Notes |
|---|---|---|
| id | UUID | primary key |
| name | varchar(64) | unique, lowercase letters, digits, `-`, `_` |
| description | text | optional |
| status | varchar(16) | `active` or `revoked` |
| api_key_hash | varchar(64) | SHA-256 of the key, unique. The raw key is never stored. |
| created_at | timestamptz | |

### Security choices

- Keys are random 256-bit tokens prefixed `ag_`, shown **once** at registration.
- Only the SHA-256 hash is stored. Since keys are high-entropy random tokens, an unsalted
  hash is safe and lets the proxy look an agent up by hash in one indexed query.
- Revoked agents get 401 immediately.
- If the database is unreachable, the proxy returns 503 and runs nothing (fail closed).
- Admin APIs need `X-Admin-Key`, checked against `AGENTGUARD_ADMIN_API_KEY_HASH`. If that is
  empty, the admin APIs reject every request. Agent keys never work as admin keys.

## Agent APIs

All need the `X-Admin-Key` header.

| Method | Path | Result |
|---|---|---|
| POST | `/api/v1/agents` | 201, the agent plus its `api_key` (only time it is shown). 409 if the name exists. |
| GET | `/api/v1/agents` | list of agents (no keys or hashes) |
| GET | `/api/v1/agents/{id}` | one agent, or 404 |
| POST | `/api/v1/agents/{id}/revoke` | agent with `status: revoked` |

To rotate a key, register a new agent and revoke the old one.

## How to use it

1. Make an admin key and put its hash in `.env`:

   ```bash
   python -c "import secrets,hashlib;k=secrets.token_urlsafe(32);print(k, hashlib.sha256(k.encode()).hexdigest())"
   # .env:  AGENTGUARD_ADMIN_API_KEY_HASH=<hash>     keep <key> somewhere safe
   ```

2. Start the stack (migrations run automatically in Compose), then register an agent:

   ```bash
   curl -s localhost:8000/api/v1/agents -H "X-Admin-Key: $ADMIN_KEY" \
     -H 'content-type: application/json' -d '{"name":"support-agent"}'
   # {"id":"...","name":"support-agent","status":"active",...,"api_key":"ag_..."}
   ```

3. Use that `api_key` as `X-API-Key` on `/api/v1/proxy/execute` ([phase-2.md](phase-2.md)).

### Run without Docker, with your own PostgreSQL

```bash
# once, in psql as a superuser:
#   CREATE USER agentguard WITH PASSWORD '...';
#   CREATE DATABASE agentguard OWNER agentguard;
export AGENTGUARD_DATABASE_URL=postgresql+psycopg://agentguard:...@localhost:5432/agentguard
export AGENTGUARD_ADMIN_API_KEY_HASH=<hash>
opa run --server --addr=127.0.0.1:8181 config/policies &   # or: docker compose up -d opa
cd backend
alembic upgrade head          # creates the agents table
uvicorn app.main:app --reload
```

`alembic downgrade base` removes the table again.

## Policy versioning

`config/policies/agentguard.rego` defines `policy_version` (currently `2026-11-22.1`). OPA adds
it to every decision; the proxy logs it and returns it as `policy_version`. **Bump it whenever
the policy changes**, so each decision can be traced to the rules that made it.

## Tests

- `backend/tests/unit/test_agents.py`: register/list/get/revoke, key shown once and stored only
  as a hash, duplicate names, admin key required, revoked agent rejected by the proxy.
- `backend/tests/unit/test_proxy.py`: database down means 503 and nothing runs.
- Unit tests use a temporary SQLite database; integration tests use real PostgreSQL with the
  Alembic migration, and real OPA.
