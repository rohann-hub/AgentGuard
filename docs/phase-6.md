# Phase 6: Human approval & refund verification

## What was built

1. **Approvals.** When policy says `approval_required`, AgentGuard stores an approval request
   and the tool does not run. An admin approves or rejects it. The agent then resubmits the
   same request with the `approval_id`, and it runs once.
2. **Refund verification.** Before policy is asked about a refund, AgentGuard checks the
   refund against trusted payments data (never the agent's word) and gives OPA the facts.
3. **Refund policy** in Rego: invalid refunds are denied, amount tiers apply, and risk
   signals send the refund to a human.

| File | Role |
|---|---|
| `backend/app/approvals/service.py` | Create, redeem (single use), expiry, request hash |
| `backend/app/api/routes/approvals.py` | Admin approval endpoints |
| `backend/app/verification/refunds.py` | Gathers refund facts from the payments source |
| `backend/app/tools/mock_payments.py` | Mock payments system (transactions, customers) |
| `backend/app/tools/registry.py` | A tool can declare a `verify` step |
| `config/policies/agentguard.rego` | Refund rules (policy version `2026-11-22.2`) |
| `backend/app/database/migrations/versions/0003_approvals.py` | `approvals` table, `audit_events.approval_id` |

## Request flow

```text
validate -> firewall -> verification (trusted data) -> OPA
  deny               -> 403, nothing runs
  approval_required  -> no approval_id: store approval, 202 {approval_id}
                        with approval_id: check it, mark used, run
  allow              -> run
```

## Refund verification

`payment.refund` now takes `transaction_id`, `customer_id`, `amount` and an optional `note`.
AgentGuard looks the transaction up in the payments source and hands OPA these facts as
`input.verification`:

| Check | Fact | Policy |
|---|---|---|
| 1. Transaction exists | `transaction_found` | deny if false or missing |
| 1b. Belongs to the customer the agent named | `customer_matches` | deny if false |
| 2. Payment completed | `payment_status` | deny unless `succeeded` |
| 3. Amount within paid / remaining balance | `refundable_balance` | deny if amount is larger |
| 4. Previous refunds | `fully_refunded`, `refunded_amount` | deny if fully refunded; partial refund is a risk signal |
| 5. Customer eligibility | `customer_eligible`, `ineligible_reasons` | deny (account not active, or older than 180 days) |
| 6. Duplicates | `refund_pending` + Phase 5 `request_id` | deny while another refund for the transaction awaits or holds approval; same `request_id` gets 409 |
| 7. Risk signals | `risk_signals` | needs approval: `new_account` (< 30 days), `high_refund_frequency` (3+ in 30 days), `previously_partially_refunded` |

Then the amount tiers, which apply only when verification passed:

| Amount | Decision |
|---|---|
| up to 5,000 | allow (unless a risk signal needs review) |
| 5,001 to 10,000 | approval required |
| over 10,000 | deny |

Deny always wins over approval, and approval over allow. A missing fact fails closed.
If the payments source cannot be reached, the request gets 503 and nothing runs.

The mock refund tool also re-checks the balance at the moment it refunds, as a real payments
provider would, so two refunds racing past verification cannot over-refund.

### Mock data

| Transaction | Customer | Paid | State | Expected |
|---|---|---|---|---|
| `txn_1001` | 101 | 12,000 | clean | ≤5,000 allow, 5,001 to 10,000 approval, >10,000 deny |
| `txn_1002` | 101 | 3,000 | fully refunded | deny |
| `txn_1003` | 101 | 5,000 | payment failed | deny |
| `txn_1004` | 102 | 4,000 | new account | approval (risk) |
| `txn_1005` | 101 | 9,000 | 2,000 already refunded | approval (risk), max 7,000 |
| `txn_1006` | 103 | 1,000 | account closed | deny |
| `txn_1007` | 101 | 2,000 | paid 400 days ago | deny |
| `txn_1008` | 104 | 1,500 | 4 refunds this month | approval (risk) |
| `txn_1009` | 101 | 2,500 | clean | allow |
| `txn_1010` | 101 | 9,500 | clean | approval above 5,000 |

The mock data lives in memory and resets when the app restarts.

### Plugging in a real payments system

Replace `app/tools/mock_payments.py` with a client offering the same three async
functions (`get_transaction`, `get_customer`, `apply_refund`). The verifier and the policy
don't change. Any other tool can get checks the same way: give its `Tool(...)` a `verify`
function and write Rego rules against `input.verification`.

## Approvals

Each approval stores the agent, tool, action, the arguments after firewall redaction (what
the reviewer sees and what will run), the policy's reason, status, expiry and decision time,
and a **request hash** of agent + tool + action + arguments.

A resubmitted request runs only if all of these hold, otherwise it gets 403:

- the approval exists and belongs to the same agent (`Approval not found`);
- the request hash matches; any changed argument fails (`Approval does not match this request`);
- it is approved and not expired (`Approval is pending` / `rejected` / `expired`);
- it has not been used (`Approval is used`). It is marked used in the same transaction as the
  audit event, under a row lock, so concurrent resubmits run it once;
- verification and OPA are re-run and still say `approval_required` (or `allow`). A refund
  that became invalid meanwhile is denied.

Expiry defaults to 1 hour (`AGENTGUARD_APPROVAL_TTL_SECONDS`).

### Admin endpoints

All need `X-Admin-Key`.

| Method | Path | Result |
|---|---|---|
| GET | `/api/v1/approvals?state=pending` | list (`pending`, `approved`, `rejected`, `used`, `expired`) |
| GET | `/api/v1/approvals/{id}` | one approval |
| POST | `/api/v1/approvals/{id}/approve` | approve a pending one; 409 otherwise |
| POST | `/api/v1/approvals/{id}/reject` | reject a pending one; 409 otherwise |

### Audit

Audit events carry `approval_id`: the `pending_approval` decision, the `executing`
decision when it is used, the result, and refused resubmits. Older events still verify.

## How to use it

```bash
# 1. agent asks: 202 with approval_id
curl -s localhost:8000/api/v1/proxy/execute -H "X-API-Key: $AGENT_KEY" -H 'content-type: application/json' \
  -d '{"request_id":"refund-1","tool_name":"payment","action":"refund","arguments":{"transaction_id":"txn_1010","customer_id":101,"amount":8000}}'
# 2. admin approves
curl -s -X POST localhost:8000/api/v1/approvals/$APPROVAL_ID/approve -H "X-Admin-Key: $ADMIN_KEY"
# 3. agent resubmits the same arguments with the approval_id and a new request_id: 200
curl -s localhost:8000/api/v1/proxy/execute -H "X-API-Key: $AGENT_KEY" -H 'content-type: application/json' \
  -d '{"request_id":"refund-1-run","approval_id":"'$APPROVAL_ID'","tool_name":"payment","action":"refund","arguments":{"transaction_id":"txn_1010","customer_id":101,"amount":8000}}'
```

Run `cd backend && alembic upgrade head` first to add the approvals table.

## Known limitations

- **One shared admin key.** Anyone with it can approve, and the approver is not recorded.
  Named approvers need user accounts (later phase).
- **The agent must resubmit.** AgentGuard does not run the tool by itself on approval.
- **Mock payments data** is in memory and resets on restart; the real source must enforce
  its own balance check, as the mock does.
- **Thresholds and risk rules are fixed** in code (verifier) and Rego. Changing them means
  editing those files and bumping `policy_version`.
- **Pending-refund lookup** scans open refund approvals in Python; fine for now, needs an
  indexed column at volume.
- Amounts are floats in the mock; real payments should use integer minor units.

## Tests

- `backend/tests/unit/test_approvals.py` (9): pending without running, approve → runs once,
  reuse refused, unapproved / rejected / expired / modified / other agent refused, policy
  re-checked on resubmit, audit chain stays valid, admin key required.
- `backend/tests/unit/test_refund_verification.py` (16): every fact from trusted data,
  pending-refund detection (excluding the approval in use), balance updated after refund,
  payments tool refuses an over-refund, verification outage fails closed.
- `backend/tests/policies/agentguard_test.rego` (17, `opa test`): every refund rule,
  tiers, risk, deny precedence, missing facts. Runs in CI.
- `backend/tests/integration/test_stack.py`: every deny reason, risk review, small refund,
  and the full approval flow (pending, duplicate refused, tamper refused, run, replay refused)
  on real PostgreSQL and OPA.
- Checked by hand: 8 concurrent resubmits of one approval gave one 200 and seven 403s.
