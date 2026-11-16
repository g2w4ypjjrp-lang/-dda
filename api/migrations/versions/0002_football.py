"""Faz 2: futbol verisi şeması.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0002_football.schema.sql")


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in (
        "football_sync_runs", "football_provider_status", "football_absences",
        "football_lineup_players", "football_lineups", "football_standings",
        "football_fixture_team_stats", "football_fixtures", "football_players", "football_teams",
        "football_venues", "football_seasons", "football_competitions", "football_countries",
    ):  # fmt: skip
        op.execute(f"DROP TABLE IF EXISTS {table}")
