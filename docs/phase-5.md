# Phase 5: Audit ledger

## What was built

Every proxied call that reaches the policy step is written to `audit_events`, an append-only,
hash-chained table in PostgreSQL.

| File | Role |
|---|---|
| `backend/app/audit/ledger.py` | Append (with chaining and duplicate detection) and verify |
| `backend/app/database/models.py` | `AuditEvent` model |
| `backend/app/database/migrations/versions/0002_audit_events.py` | Table, unique index, PL/pgSQL triggers |
| `backend/app/api/routes/audit.py` | Admin endpoints |
| `backend/app/api/routes/proxy.py` | Writes events at each outcome |

### What is recorded, and when

| Outcome | Events |
|---|---|
| Allowed and executed | `decision` (`status: executing`) **before** the tool runs, then `execution` (`success` / `failed` / `blocked`) after |
| Denied by policy | one `decision` (`blocked`) |
| Approval required | one `decision` (`pending_approval`) |
| Secret in arguments | one `decision` (`blocked`, no policy decision) |
| OPA unavailable | one `error` event |

Each event stores: sequence number, time, request_id, agent id and name, tool, action, event
type, policy decision, status, reason, policy version, firewall findings (type, path, action),
a SHA-256 fingerprint of the **redacted** arguments, a fingerprint of the **redacted** tool
result, the previous event's hash and its own hash.

### Privacy

No raw arguments, results, API keys, passwords, secrets or PII are stored:
- arguments and results are stored only as fingerprints, computed after firewall redaction;
- firewall findings hold the entity type and location, never the value;
- the `reason` text (which can echo a tool error) passes through the firewall before storage.

### Fail closed

| Failure | Behavior |
|---|---|
| Pre-execution `decision` event cannot be written | 503 `Audit unavailable`; **the tool does not run** |
| Post-execution `execution` event cannot be written | 503; the tool already ran, but **its result is withheld** from the agent |
| Any other event cannot be written | 503 instead of the normal answer; nothing runs |

### Duplicate protection (idempotency)

`request_id` is the idempotency key. A unique index on `(agent_id, request_id)` for
`decision` events means each agent can get a request decided once. A retry with the same
`request_id` gets **409**, so the tool never runs twice, even under concurrent retries.
Exceptions that let a retry through: OPA was down (`error` event) or the audit write failed
(nothing was written). Request ids are per agent.

### Tamper detection

`event_hash = SHA-256(prev_hash + canonical JSON of the event)`, starting from 64 zeros.
`GET /api/v1/audit/verify` recomputes the chain and reports the first bad event. Changing any
field, deleting an event, or reordering events breaks verification from that point.

### Database protection (PL/pgSQL)

Migration `0002` installs `audit_events_append_only()`, a PL/pgSQL trigger function, on
`BEFORE UPDATE OR DELETE` (per row) and `BEFORE TRUNCATE`. The application can only insert;
any update, delete or truncate raises `audit_events is append-only`.

Appends take a PostgreSQL advisory lock, so concurrent requests (even across app instances)
build one unbroken chain.

## Admin endpoints

Both need `X-Admin-Key`.

| Method | Path | Result |
|---|---|---|
| GET | `/api/v1/audit?limit=100&request_id=…` | newest events first (limit 1 to 1000) |
| GET | `/api/v1/audit/verify` | `{"valid": true, "events": 89, "first_invalid_seq": null}` |

## How to use it

```bash
cd backend && alembic upgrade head      # adds audit_events and the triggers
curl -s localhost:8000/api/v1/audit/verify -H "X-Admin-Key: $ADMIN_KEY"
curl -s "localhost:8000/api/v1/audit?request_id=req_001" -H "X-Admin-Key: $ADMIN_KEY"
```

Send a `request_id` with every proxy call you might retry; that is what makes retries safe.

## Known limitations

- **Superusers can still tamper.** The triggers stop the application role; a database
  superuser can disable them. The hash chain still exposes edits, but not deletion of the
  newest events or a fully rewritten chain. Production should add signed checkpoints or
  ship hashes to external immutable storage, and run the app as a non-owner role.
- **No `request_id`, no retry protection.** When the agent omits it, a fresh id is generated
  for every call.
- **Duplicates are rejected, not replayed.** A retry gets 409, not the original response.
- **Requests rejected before the policy step** (bad key, unknown tool, invalid arguments)
  are not recorded; they never reach a tool.
- **Tool results are fingerprinted, not stored,** because undetected PII (names, addresses)
  could otherwise land in the ledger. Storing the redacted result is a small change if wanted.
- **Verify reads the whole chain**; fine for now, needs checkpoints at large volumes.
- `alembic downgrade` below `0002` drops the audit table and its history.

## Tests

- `backend/tests/unit/test_audit.py` (17 tests): events for each outcome, pre-execution
  audit failure stops the tool, post-execution failure withholds the result, duplicates
  (same agent, across agents, after deny, retry after OPA outage), no raw secrets or PII in
  stored rows or the admin API, valid chain, modified and deleted events detected, admin key required.
- `backend/tests/integration/test_stack.py`: duplicate 409, chain verifies, and the PL/pgSQL
  triggers reject UPDATE, DELETE and TRUNCATE on real PostgreSQL.
- Checked by hand: 40 concurrent requests plus 10 concurrent retries of one `request_id`
  (one 200, nine 409) left a valid chain.
