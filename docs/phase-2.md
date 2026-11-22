# Phase 2: Tool gateway

## What was built

`POST /api/v1/proxy/execute` is the only path from an agent to a tool.

| File | Role |
|---|---|
| `backend/app/api/routes/proxy.py` | The endpoint and the request pipeline |
| `backend/app/auth/api_keys.py` | Agent authentication by `X-API-Key` |
| `backend/app/tools/registry.py` | The only tools that can run, keyed by `(tool_name, action)` |
| `backend/app/tools/mock_tools.py` | Mock customer database and payment tools |
| `backend/app/policy/opa_client.py` | Asks OPA for a decision; any failure denies |
| `backend/app/schemas/proxy.py` | Request and response bodies |
| `config/policies/agentguard.rego` | The policy |

## How a request is processed

1. **Authenticate.** The `X-API-Key` header identifies the agent. The agent's identity never
   comes from the body; unknown body fields (such as `agent_id`) are rejected with 422.
2. **Look up the tool.** `(tool_name, action)` must be in the registry, otherwise 404.
   Names are looked up in a dict, never imported or called dynamically.
3. **Validate arguments** with the tool's strict Pydantic model (extra fields rejected), otherwise 422.
   This happens before OPA is asked, so the policy only ever sees well-formed input.
4. **Ask OPA** with `{agent, tool_name, action, arguments}`.
5. **Execute** only when OPA says `allow`, under a timeout (`AGENTGUARD_TOOL_TIMEOUT_SECONDS`, default 5).

| Tool call | Policy | HTTP | Tool runs? |
|---|---|---|---|
| `database.read` | allow | 200 `success` | yes |
| `database.delete` | deny | 403 `blocked` | no |
| `payment.refund` | approval required | 202 `pending_approval` | no |
| not in the registry | | 404 | no |
| OPA down, slow, or invalid answer | deny | 503 `blocked` | no |
| missing, wrong or revoked key | | 401 | no |
| tool error / timeout / crash | allow | 422 / 504 / 500 `failed` | started |

Crash messages are never returned to the agent. Tool arguments are never logged, since they may
hold PII or secrets.

### Policy

Rules add reasons to three sets: `deny`, `approval_required`, `allow`. The decision takes the
first non-empty set in that order, so **deny always wins**, and anything no rule covers is denied.

## How to use it

Register an agent (see [phase-3.md](phase-3.md)), then:

```bash
curl -s localhost:8000/api/v1/proxy/execute \
  -H "X-API-Key: $AGENT_KEY" -H 'content-type: application/json' \
  -d '{"request_id":"req_001","tool_name":"database","action":"read","arguments":{"customer_id":101}}'
```

```json
{"request_id":"req_001","status":"success","decision":"allow","policy_version":"2026-11-22.1",
 "tool_result":{"customer":{"customer_id":101,"name":"Asha Rao","plan":"pro"}}}
```

`request_id` is optional; one is generated when missing. Mock customers are 101 and 102.
Since Phase 4 the customer record also has an email and phone, which the firewall redacts
(see [phase-4.md](phase-4.md)). Since Phase 6, `payment.refund` also needs a
`transaction_id` and is verified first (see [phase-6.md](phase-6.md)).

### Adding a tool

Write an async handler and a Pydantic args model (`extra="forbid"`), add one `Tool(...)` line to
`_TOOLS` in `registry.py`, and add a rule for it in the Rego policy. Without a rule it is denied.

## Not done yet

- Idempotency (deduplicating repeated `request_id`s).
- Approval requests are not stored; `pending_approval` just means the tool did not run (Phase 6).
- Amount-based refund limits from the design doc (easy to add in Rego when wanted).

## Tests

`backend/tests/unit/test_proxy.py` covers every row of the table above, with a spy that proves
whether the tool ran. `backend/tests/integration/test_stack.py` runs read, delete and refund
through the real stack and real OPA.
