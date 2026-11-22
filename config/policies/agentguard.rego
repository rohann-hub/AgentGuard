# AgentGuard tool policy. Input: {agent, tool_name, action, arguments}.
# Precedence: deny > approval_required > allow > default deny.
package agentguard

import rego.v1

default decision := {
	"status": "deny",
	"reason": "No matching policy (default deny)",
}

decision := {"status": "deny", "reason": concat("; ", sort(deny))} if {
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

approval_required contains "Refunds require human approval" if {
	input.tool_name == "payment"
	input.action == "refund"
}
