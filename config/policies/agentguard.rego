# AgentGuard tool policy. Input: {agent, tool_name, action, arguments, firewall, verification}.
# Precedence: deny > approval_required > allow > default deny.
package agentguard

import rego.v1

# Bump on every policy change; it is returned with each decision.
policy_version := "2026-11-22.2"

decision := object.union(result, {"policy_version": policy_version})

default result := {
	"status": "deny",
	"reason": "No matching policy (default deny)",
}

result := {"status": "deny", "reason": concat("; ", sort(deny))} if {
	count(deny) > 0
} else := {"status": "approval_required", "reason": concat("; ", sort(approval_required))} if {
	count(approval_required) > 0
} else := {"status": "allow", "reason": concat("; ", sort(allow))} if {
	count(allow) > 0
}

allow contains "Customer reads are permitted" if {
	input.tool_name == "database"
	input.action == "read"
}

deny contains "Deleting customer data is prohibited" if {
	input.tool_name == "database"
	input.action == "delete"
}

# --- Refunds ---------------------------------------------------------------
# input.verification holds facts AgentGuard read from the trusted payments system.
# A missing fact fails closed: "not v.transaction_found" is true when it is absent.

refund_auto_approve_limit := 5000

refund_max_amount := 10000

is_refund if {
	input.tool_name == "payment"
	input.action == "refund"
}

v := object.get(input, "verification", {})

amount := input.arguments.amount

deny contains "Transaction not found" if {
	is_refund
	not v.transaction_found
}

deny contains "Transaction belongs to a different customer" if {
	is_refund
	v.transaction_found
	not v.customer_matches
}

deny contains "Original payment was not completed" if {
	is_refund
	v.transaction_found
	v.payment_status != "succeeded"
}

deny contains "Transaction is already fully refunded" if {
	is_refund
	v.fully_refunded
}

deny contains "Refund exceeds the refundable balance" if {
	is_refund
	v.transaction_found
	amount > v.refundable_balance
}

deny contains sprintf("Customer is not eligible: %s", [concat(", ", v.ineligible_reasons)]) if {
	is_refund
	v.transaction_found
	not v.customer_eligible
}

deny contains "A refund for this transaction is already pending" if {
	is_refund
	v.refund_pending
}

deny contains sprintf("Refund exceeds the maximum of %d", [refund_max_amount]) if {
	is_refund
	amount > refund_max_amount
}

approval_required contains sprintf("Refunds over %d require human approval", [refund_auto_approve_limit]) if {
	is_refund
	amount > refund_auto_approve_limit
}

approval_required contains sprintf("Risk signals: %s", [concat(", ", sort(v.risk_signals))]) if {
	is_refund
	count(v.risk_signals) > 0
}

allow contains "Refund passed verification" if {
	is_refund
	v.transaction_found
}
