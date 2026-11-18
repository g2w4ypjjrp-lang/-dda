"""Olay döngüsü yardımcısı.

psycopg'nin asenkron sürücüsü Windows'un varsayılan ``ProactorEventLoop``'u ile çalışmaz; uvicorn
0.54 de Windows'ta Proactor seçer. Windows'ta (tek sunucu kurulumu, deploy/windows) tüm asenkron
çalıştırmalar ``SelectorEventLoop`` ile yapılır. Linux/macOS'ta davranış değişmez.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

WINDOWS = sys.platform == "win32"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    if WINDOWS:
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)
