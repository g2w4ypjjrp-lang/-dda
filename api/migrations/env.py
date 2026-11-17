"""Alembic ortamı: senkron psycopg bağlantısı, adres ``MI_DATABASE_URL``'den.

Geçişler ORM modellerinden otomatik üretilmez; her geçiş elle yazılmış SQL'dir (CHECK
kısıtları, tetikleyiciler ve tohum verisi gözden geçirilerek eklenir).
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    url = config.attributes.get("database_url") or os.environ.get("MI_DATABASE_URL")
    if not url:
        raise RuntimeError("MI_DATABASE_URL tanımlı değil")
    return str(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
