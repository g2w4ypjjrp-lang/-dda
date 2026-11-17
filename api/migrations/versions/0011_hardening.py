"""Faz 10: dört göz onayı ve yedek kayıtları.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0011_hardening.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE backups, approval_requests; DELETE FROM feature_flags WHERE key = 'dual_control'")
