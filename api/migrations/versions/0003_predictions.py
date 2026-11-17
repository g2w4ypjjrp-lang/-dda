"""Faz 3: model kayıt defteri ve değiştirilemez tahminler.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0003_predictions.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("Tahmin geçmişi geri alınamaz (değiştirilemez kayıtlar); yedekten geri yükleyin")
