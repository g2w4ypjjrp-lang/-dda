"""Faz 8: tasarım sistemleri ve Design Studio sürümleri.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17
"""

import json
from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0008_design.schema.sql")


def upgrade() -> None:
    from mi_api.design.defaults import DEFAULT_KEY, DEFAULTS, ORDER
    from mi_api.design.schema import DesignConfig

    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))
    for key in ORDER:
        config = DesignConfig.model_validate(DEFAULTS[key]).model_dump(mode="json")
        raw.execute(
            "INSERT INTO design_versions (design_key, version, status, config, note, published_at)"
            " VALUES (%s, 1, 'published', %s, 'İlk sürüm', now())",
            (key, json.dumps(config)),
        )
    raw.execute("INSERT INTO design_settings (id, default_design) VALUES (1, %s)", (DEFAULT_KEY,))


def downgrade() -> None:
    raise RuntimeError("Tasarım sürüm geçmişi geri alınamaz; yedekten geri yükleyin")
