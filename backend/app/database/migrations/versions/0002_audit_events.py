"""Create audit_events (append-only, hash-chained).

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# PL/pgSQL guard: the app can only INSERT audit events. UPDATE, DELETE and TRUNCATE fail,
# so tampering needs a database superuser (and still breaks the hash chain).
_IMMUTABLE = """
CREATE FUNCTION audit_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
END;
$$;
CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False, index=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=True),
        sa.Column("firewall", sa.JSON(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response_fingerprint", sa.String(64), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index(
        "uq_audit_decision_request",
        "audit_events",
        ["agent_id", "request_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'decision'"),
        sqlite_where=sa.text("event_type = 'decision'"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_IMMUTABLE)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER audit_events_no_truncate ON audit_events")
        op.execute("DROP TRIGGER audit_events_no_update_delete ON audit_events")
        op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_table("audit_events")
