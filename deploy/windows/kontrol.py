"""CI (windows-latest): Windows'ta olay döngüsü ve veritabanı sürücüsü kontrolü."""

import asyncio
import sys

import psycopg  # noqa: F401  (Windows tekerleği yüklenebiliyor mu)

from mi_api import aio


async def kind() -> type:
    return type(asyncio.get_running_loop())


assert aio.WINDOWS, "Bu kontrol Windows'ta çalışır"
assert issubclass(aio.run(kind()), asyncio.SelectorEventLoop), "psycopg için Selector döngüsü gerekli"
print("ok", sys.version)
