"""Alembic geçişlerini kod içinden çalıştırma ve şema durumunu sorgulama."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

API_ROOT = Path(__file__).resolve().parents[2]


def sync_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.attributes["database_url"] = sync_url(url)
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def head_revision() -> str | None:
    script = ScriptDirectory.from_config(alembic_config("postgresql://unused/unused"))
    return script.get_current_head()


def current_revision(url: str) -> str | None:
    engine = create_engine(sync_url(url), connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            try:
                return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except ProgrammingError:
                return None
    finally:
        engine.dispose()
