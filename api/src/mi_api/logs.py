"""Yapılandırılmış (JSON) loglama, gizli değer maskeleme ve istek kimliği.

Maskeleme iki katmanlıdır: anahtar adına göre (``password``, ``token``, ``secret`` ...) ve değer
biçimine göre (``Bearer`` belirteçleri, uzun rastgele dizgiler). Denetim kaydı ayrıntıları da
yazılmadan önce aynı fonksiyondan geçer.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import secrets
import sys
import time
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_SENSITIVE_KEYS = re.compile(
    r"passw(or)?d|^pass$|secret|token|authorization|cookie|totp|api[_-]?key|kek|signature|"
    r"recovery|^code$|^otp$",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_LONG_RANDOM = re.compile(r"\b[A-Za-z0-9_-]{40,}\b")
MASK = "***"


def redact(value: Any, *, _key: str | None = None) -> Any:
    if _key is not None and _SENSITIVE_KEYS.search(_key):
        return MASK
    if isinstance(value, dict):
        return {k: redact(v, _key=str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _LONG_RANDOM.sub(MASK, _BEARER.sub("Bearer " + MASK, value))
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            entry["request_id"] = rid
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update(redact(extra))
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_RID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
access_log = logging.getLogger("mi_api.access")


class RequestContext:
    """Her isteğe ``X-Request-ID`` atar (gelen değer biçime uyuyorsa korunur) ve erişim logu yazar.

    Güvenlik başlıkları da burada eklenir (API JSON döner; tarayıcıda çalıştırılacak içerik yok).
    """

    def __init__(self, app: ASGIApp, metrics: Any = None) -> None:
        self.app = app
        self.metrics = metrics  # mi_api.ops.metrics.Metrics (isteğe bağlı)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _RID_PATTERN.match(incoming) else secrets.token_hex(8)
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                extra = [
                    (b"x-request-id", rid.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                # Varsayılan önbelleksiz; açıkça önbellek başlığı koyan uç (ör. /v1/design) korunur.
                if not any(k.lower() == b"cache-control" for k, _ in message.get("headers", [])):
                    extra.append((b"cache-control", b"no-store"))
                # JSON API: hiçbir şey yüklenmez ve çerçevelenmez. /docs (yalnızca geliştirme)
                # Swagger arayüzü dış betik yüklediği için hariç.
                if not scope["path"].startswith("/docs"):
                    extra.append(
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
                    )
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            if self.metrics is not None:
                await self.metrics.record(
                    scope["method"], scope["path"], status_holder["status"], elapsed, rid
                )
            access_log.info(
                "request",
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status_holder["status"],
                        "duration_ms": round(elapsed, 1),
                    }
                },
            )
            request_id_var.reset(token)
