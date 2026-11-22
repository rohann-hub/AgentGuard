# Base AgentGuard policy. Deny by default; real rules arrive in Phase 3.
package agentguard

import rego.v1

default allow := false

decision := {
	"allow": allow,
	"reason": "no matching policy (default deny)",
}
