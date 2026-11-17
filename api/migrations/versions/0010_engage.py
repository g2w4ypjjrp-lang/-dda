"""Faz 7: favoriler, bildirimler, panel düzeni, içerik (SSS, yasal sayfalar).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17
"""

from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0010_engage.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE faq_items, content_pages, dashboard_layouts, notification_prefs, notifications, user_favorites")
