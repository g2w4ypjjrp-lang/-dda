"""Faz 9: yönetim operasyonları (özellik bayrakları, Action Center, kayıtlı filtreler).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0009_ops.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE admin_saved_filters, admin_action_acks, feature_flags")
