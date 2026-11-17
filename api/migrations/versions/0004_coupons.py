"""Faz 4: değiştirilemez kupon geçmişi.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0004_coupons.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("Kupon geçmişi geri alınamaz (değiştirilemez kayıtlar); yedekten geri yükleyin")
