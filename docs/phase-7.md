# Phase 7: End-to-end testing & hardening

Phases 2 to 6 already test authentication, allow / deny / approval, PII, secrets, tool
failures, OPA failure, the audit chain and duplicate requests. Phase 7 adds what was missing:
one end-to-end story, bypass attempts, real outages, and a request size limit.

## What was built

| File | Role |
|---|---|
| `backend/app/api/limits.py` | Rejects bodies over 64 KB with 413 before anything reads them |
| `backend/tests/integration/test_e2e_scenarios.py` | The design doc's demo on the real stack |
| `backend/tests/unit/test_bypass.py` | Attempts to get around the gateway |
| `backend/tests/outage/test_outages.py` | Stops and restarts OPA and PostgreSQL |
| `scripts/demo.sh` | The demo with curl, to watch it work |
| `.github/workflows/tests.yml` | New `outage` CI job |

### Request size limit

Bodies over `AGENTGUARD_MAX_REQUEST_BYTES` (default 65,536) get **413** before
authentication, parsing or any other work. It checks the `Content-Length` header and also
counts bytes for chunked uploads that have none. An invalid `Content-Length` gets 400.

### Stricter argument types

Tool argument models now use Pydantic strict mode: `"101"` or `true` is no longer accepted
as a customer id. The bypass tests found that `true` was being coerced to `1`.

## The end-to-end scenarios

`test_e2e_scenarios.py` registers a fresh agent and runs:

1. Read customer: **allow**, executed, email and phone redacted, audit shows decision then result.
2. Delete customer: **deny**, not executed, one audit event.
3. Refund 8,000 on `txn_1011`: **approval required**. A resubmit before approval is
   refused. An admin approves. The resubmit runs once and a replay is refused.
4. AWS key in a refund note: **blocked**, and the key appears in neither the response nor the audit log.
5. The audit chain verifies.

## Bypass attempts (all must fail, no tool runs)

| Attempt | Result |
|---|---|
| `agent_id` / `agent` / `agent_name` in the body | 422 |
| `X-Agent-Id`, `X-Forwarded-User` headers | ignored; identity still comes from the key |
| API key in the query string | 401 |
| Agent key on `/agents`, `/audit`, `/approvals` | 401 |
| Tool names `Database`, ` database`, Cyrillic `а`, NUL byte, `../database` | 404, OPA never asked |
| Actions `Read`, `read;delete`, `__init__`, `handler` | 404 |
| Nested or extra arguments, lists, SQL in an id, `1e30`, `true` | 422, OPA never asked |
| Arguments as a list; form-encoded body | 422 |
| Refund naming a different customer than the transaction's | verification reports the mismatch, policy denies |
| Body over 64 KB (sized or chunked) | 413 |

Reusing another agent's approval, modifying an approved request and replaying an approval
are covered in `test_approvals.py` (Phase 6).

## Outage tests

`pytest -m outage` runs against a live Compose stack and uses `docker compose stop/start`:

- **OPA down:** `/health/ready` is 503, a read and a refund both get 503
  `Policy engine unavailable`, nothing runs. After restart the same `request_id` is retried
  and runs; the audit shows `error`, `decision`, `execution`.
- **PostgreSQL down:** `/health/ready` is 503, requests get 503, nothing runs. After restart
  requests work again.
- **The audit chain still verifies** after both outages.

They run in a separate `outage` CI job so the normal `stack` job stays fast.

## How to run it

```bash
docker compose up -d --build --wait
pytest -m integration         # stack tests, including the e2e scenarios
pytest -m outage              # stops/starts OPA and Postgres; run on its own
ADMIN_KEY=<admin key> ./scripts/demo.sh
```

The demo refunds mock transaction `txn_1011` for real; restart the backend to reset the mock
data (`docker compose restart backend`).

## Not in this phase

- **Rate limiting** is left to Phase 10, done properly with Redis across instances.
- Integration and outage tests share the stack's in-memory mock data; run them on a fresh
  stack (as CI does) or restart the backend between runs.

## Tests

- 144 unit tests (30 new bypass and size-limit tests).
- 28 stack tests (5 new end-to-end scenarios).
- 3 outage tests.
- 17 OPA policy tests.
