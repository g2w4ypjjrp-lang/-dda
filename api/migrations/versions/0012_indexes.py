"""Faz 10: EXPLAIN incelemesiyle eklenen indeksler.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0012_indexes.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        "DROP INDEX ix_user_sessions_user_created, ix_audit_log_actor_id, ix_audit_log_target_id,"
        " ix_audit_log_action_prefix, ix_subscriptions_active_end"
    )
