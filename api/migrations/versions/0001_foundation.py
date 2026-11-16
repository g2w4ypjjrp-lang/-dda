"""Faz 1 temel şema: kimlik, oturum, MFA, RBAC, denetim kaydı, e-posta kuyruğu.

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0001_foundation.schema.sql")


def upgrade() -> None:
    # Ham SQL, parametresiz olarak tek parça çalıştırılır (fonksiyon gövdelerinde ';' ve
    # LIKE kalıplarında '%' bulunur; sürücünün yer tutucu işlemesine girmemeli).
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("Temel şema geri alınamaz; yedekten geri yükleyin")
