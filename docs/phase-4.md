# Phase 4: PII & secret firewall

## What was built

Every tool call is scanned twice: the **arguments** (before OPA and before the tool) and the
**tool response** (before it goes back to the agent).

| File | Role |
|---|---|
| `backend/app/firewall/detectors.py` | Patterns and checksum validators |
| `backend/app/firewall/scanner.py` | Walks JSON, applies block / redact / allow, reports findings |
| `backend/app/api/routes/proxy.py` | Calls the scanner on arguments and responses |

### What it detects

| Type | Entity | How |
|---|---|---|
| PII | `EMAIL` | pattern |
| PII | `PHONE` | pattern, 10 to 13 digits |
| PII | `CREDIT_CARD` | pattern + Luhn checksum |
| PII | `IN_AADHAAR` | pattern + Verhoeff checksum |
| PII | `IN_PAN` | PAN format (holder-type letter checked) |
| Secret | `AWS_ACCESS_KEY`, `GITHUB_TOKEN`, `SLACK_TOKEN`, `JWT`, `PRIVATE_KEY` | known formats |
| Secret | `API_KEY` | `sk-…`, `sk_live_…`/`sk_test_…`, AgentGuard `ag_…` keys |
| Secret | `SECRET_FIELD` | any string in a field named like `password`, `secret`, `token`, `api_key`, `credential` |

Checksums mean random digit runs (order numbers, dates, amounts) are not flagged as cards or
Aadhaar numbers. Only strings are scanned; numbers pass through.

### Actions

| Default | Effect |
|---|---|
| Secrets: `block` | Arguments: 403, OPA is never asked, the tool never runs. Response: 403, the result is withheld. |
| PII: `redact` | The value is replaced with `[REDACTED:<TYPE>]`. The tool and OPA see the redacted arguments; the agent gets the redacted response. |

Override per entity type with `AGENTGUARD_FIREWALL_ACTIONS` (JSON), e.g.
`AGENTGUARD_FIREWALL_ACTIONS={"EMAIL":"allow","PHONE":"block"}`. Allowed actions: `block`,
`redact`, `allow`.

### What the agent sees

Findings report the type, where it was found, and the action. **Never the value.**

```json
{"request_id":"req_…","status":"success","decision":"allow","policy_version":"2026-11-22.1",
 "tool_result":{"customer":{"customer_id":101,"name":"Asha Rao",
   "email":"[REDACTED:EMAIL]","phone":"[REDACTED:PHONE]","plan":"pro"}},
 "firewall":[{"entity_type":"EMAIL","path":"tool_result.customer.email","action":"redact"},
             {"entity_type":"PHONE","path":"tool_result.customer.phone","action":"redact"}]}
```

### Policy can see findings

OPA input now includes `"firewall": ["EMAIL", ...]`, the entity types found in the arguments,
so a Rego rule can deny or require approval when, say, a refund note contains PII.

## How to use it

```bash
curl -s localhost:8000/api/v1/proxy/execute -H "X-API-Key: $AGENT_KEY" -H 'content-type: application/json' \
  -d '{"tool_name":"payment","action":"refund","arguments":{"customer_id":101,"amount":10,"note":"key AKIAIOSFODNN7EXAMPLE"}}'
# 403 {"status":"blocked","reason":"Sensitive data in arguments","firewall":[{"entity_type":"AWS_ACCESS_KEY",...}]}
```

`payment.refund` gained an optional `note` field (free text, max 500 chars).

## Limits

- Pattern + checksum detectors only. Names and addresses in free text are not detected.
  Presidio + spaCy can be added behind the same `find()` interface when needed.
- Findings are not stored yet; the audit ledger (Phase 5) will record them, without values.

## Tests

- `backend/tests/unit/test_firewall.py`: every detector, checksum rejection, ordinary text not
  flagged, nested redaction with paths, secret-named fields, overrides.
- `backend/tests/unit/test_proxy.py`: secret in arguments blocks before OPA, PII redacted
  before OPA and tool, configurable actions, secret in a tool response blocks.
- `backend/tests/integration/test_stack.py`: redacted response and blocked secret on the real stack.
