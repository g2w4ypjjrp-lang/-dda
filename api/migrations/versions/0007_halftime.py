"""İlk yarı modeli: tahmin sonuçlarına İY skoru ve İY metrikleri.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0007_halftime.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("Sonuç kayıtları değiştirilemez; geri almak için yedekten geri yükleyin")
