# Policy unit tests: `opa test config/policies backend/tests/policies -v`
package agentguard_test

import rego.v1

import data.agentguard

ok := {
	"transaction_found": true,
	"customer_matches": true,
	"payment_status": "succeeded",
	"refundable_balance": 20000,
	"fully_refunded": false,
	"customer_eligible": true,
	"ineligible_reasons": [],
	"refund_pending": false,
	"risk_signals": [],
}

refund(amount, facts) := {
	"tool_name": "payment",
	"action": "refund",
	"arguments": {"amount": amount},
	"verification": facts,
}

status(input_doc) := s if {
	s := agentguard.decision.status with input as input_doc
}

reason(input_doc) := r if {
	r := agentguard.decision.reason with input as input_doc
}

test_read_allowed if status({"tool_name": "database", "action": "read"}) == "allow"

test_delete_denied if status({"tool_name": "database", "action": "delete"}) == "deny"

test_unknown_tool_denied if status({"tool_name": "shell", "action": "exec"}) == "deny"

test_decision_carries_policy_version if {
	agentguard.decision.policy_version == agentguard.policy_version with input as {}
}

# --- refund amount tiers (verification passed) ---

test_small_refund_allowed if status(refund(5000, ok)) == "allow"

test_mid_refund_needs_approval if status(refund(5001, ok)) == "approval_required"

test_large_refund_denied if reason(refund(10001, ok)) == "Refund exceeds the maximum of 10000"

# --- verification failures deny, whatever the amount ---

test_missing_verification_denied if reason(refund(10, null)) == "Transaction not found"

test_unknown_transaction_denied if reason(refund(10, {"transaction_found": false})) == "Transaction not found"

test_wrong_customer_denied if {
	reason(refund(10, object.union(ok, {"customer_matches": false}))) == "Transaction belongs to a different customer"
}

test_failed_payment_denied if {
	reason(refund(10, object.union(ok, {"payment_status": "failed"}))) == "Original payment was not completed"
}

test_over_balance_denied if {
	reason(refund(600, object.union(ok, {"refundable_balance": 500}))) == "Refund exceeds the refundable balance"
}

test_fully_refunded_denied if {
	facts := object.union(ok, {"fully_refunded": true, "refundable_balance": 0})
	status(refund(10, facts)) == "deny"
}

test_ineligible_customer_denied if {
	facts := object.union(ok, {"customer_eligible": false, "ineligible_reasons": ["outside the refund window"]})
	reason(refund(10, facts)) == "Customer is not eligible: outside the refund window"
}

test_pending_refund_denied if {
	reason(refund(10, object.union(ok, {"refund_pending": true}))) == "A refund for this transaction is already pending"
}

# --- risk sends even small refunds to a human; deny still wins ---

test_risk_signal_needs_approval if {
	reason(refund(100, object.union(ok, {"risk_signals": ["new_account"]}))) == "Risk signals: new_account"
}

test_deny_beats_risk if {
	facts := object.union(ok, {"risk_signals": ["new_account"], "payment_status": "failed"})
	status(refund(100, facts)) == "deny"
}
