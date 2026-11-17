"""Faz 6: paketler, abonelikler, ödeme ve lisanslar.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0006_billing.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("Ödeme ve abonelik kayıtları geri alınamaz (değiştirilemez kayıtlar); yedekten geri yükleyin")
