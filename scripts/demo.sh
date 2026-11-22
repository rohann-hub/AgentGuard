#!/usr/bin/env bash
# Walks the AgentGuard demo against a running stack.
# Usage: ADMIN_KEY=<your admin key> ./scripts/demo.sh   (BASE_URL defaults to localhost:8000)
# Note: it really refunds mock transaction txn_1011; restart the backend to reset mock data.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
: "${ADMIN_KEY:?set ADMIN_KEY to the admin key whose hash is in AGENTGUARD_ADMIN_API_KEY_HASH}"

json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
call() {  # call <request-id> <json body without request_id>
  curl -s "$BASE_URL/api/v1/proxy/execute" -H "X-API-Key: $AGENT_KEY" \
    -H 'content-type: application/json' -d "{\"request_id\":\"$1\",${2#\{}"
  echo
}
admin() { curl -s -X "$1" "$BASE_URL$2" -H "X-Admin-Key: $ADMIN_KEY"; echo; }

RUN="demo-$(date +%s)"
REFUND='{"tool_name":"payment","action":"refund","arguments":{"transaction_id":"txn_1011","customer_id":101,"amount":8000}}'

step "Register an agent"
AGENT_KEY=$(curl -s "$BASE_URL/api/v1/agents" -H "X-Admin-Key: $ADMIN_KEY" \
  -H 'content-type: application/json' -d "{\"name\":\"$RUN\"}" | json '["api_key"]')
echo "agent $RUN registered"

step "1. Read customer: ALLOW, executed, PII redacted"
call "$RUN-read" '{"tool_name":"database","action":"read","arguments":{"customer_id":101}}'

step "2. Delete customer: DENY, not executed"
call "$RUN-delete" '{"tool_name":"database","action":"delete","arguments":{"customer_id":101}}'

step "3. Refund 8,000: APPROVAL REQUIRED, not executed"
ASK=$(call "$RUN-refund" "$REFUND")
echo "$ASK"
APPROVAL_ID=$(echo "$ASK" | json '["approval_id"]')

step "4. Admin approves $APPROVAL_ID"
admin POST "/api/v1/approvals/$APPROVAL_ID/approve"

step "5. Agent resubmits with the approval: executed once"
WITH_APPROVAL="{\"approval_id\":\"$APPROVAL_ID\",${REFUND#\{}"
call "$RUN-refund-run" "$WITH_APPROVAL"

step "6. Replaying the approval: refused"
call "$RUN-refund-replay" "$WITH_APPROVAL"

step "7. Secret in arguments: BLOCKED by the firewall"
call "$RUN-secret" '{"tool_name":"payment","action":"refund","arguments":{"transaction_id":"txn_1009","customer_id":101,"amount":5,"note":"key AKIAIOSFODNN7EXAMPLE"}}'

step "8. Audit chain"
admin GET /api/v1/audit/verify
