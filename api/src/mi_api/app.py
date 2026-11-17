"""Uygulama fabrikası."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from mi_api import __version__
from mi_api.admin.router import create_admin_router
from mi_api.auth.router import create_auth_router
from mi_api.billing.api import create_billing_router
from mi_api.config import Settings
from mi_api.context import Clock, Services, utcnow
from mi_api.coupons.api import create_coupons_router
from mi_api.db import Database
from mi_api.errors import install_error_handlers
from mi_api.football.api import create_football_router
from mi_api.football.runtime import FootballRuntime
from mi_api.guards import RequestGuard
from mi_api.logs import RequestContext
from mi_api.migrate import current_revision, head_revision
from mi_api.predictions.api import create_predictions_router
from mi_api.ratelimit import Limiter, MemoryLimiter, RedisLimiter
from mi_api.virtual.api import create_virtual_router


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock = utcnow,
    limiter: Limiter | None = None,
    football_transport: httpx.AsyncBaseTransport | None = None,
    payment_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    cfg = settings or Settings()
    db = Database(cfg.database_url.get_secret_value())
    redis = Redis.from_url(cfg.redis_url.get_secret_value()) if cfg.redis_url else None
    if limiter is None:
        limiter = RedisLimiter(redis) if redis is not None else MemoryLimiter()
    services = Services.build(cfg, db, limiter, clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await db.close()
        if redis is not None:
            await redis.aclose()

    app = FastAPI(
        title="Match Intelligence AI",
        version=__version__,
        # Üretimde API şeması herkese açık yayımlanmaz.
        docs_url=None if cfg.is_production_like else "/docs",
        redoc_url=None,
        openapi_url=None if cfg.is_production_like else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.services = services
    app.state.football = FootballRuntime(
        cfg, clock=clock, redis=redis, transport=football_transport
    )
    app.state.payment_transport = payment_transport
    app.add_middleware(RequestGuard, web_origins=cfg.web_origins, admin_origins=cfg.admin_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys([*cfg.web_origins, *cfg.admin_origins])),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContext)
    install_error_handlers(app)
    app.include_router(create_auth_router())
    app.include_router(create_admin_router())
    app.include_router(create_football_router())
    app.include_router(create_predictions_router())
    app.include_router(create_coupons_router())
    app.include_router(create_virtual_router())
    app.include_router(create_billing_router())

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Canlılık: süreç ayakta mı?"""
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["system"])
    async def ready() -> JSONResponse:
        """Hazırlık: veritabanı erişilebilir, şema güncel ve (varsa) Redis yanıt veriyor mu?"""
        checks: dict[str, Any] = {}
        ok = True
        try:
            async with db.session() as session:
                await session.execute(text("SELECT 1"))
            current = await asyncio.to_thread(current_revision, cfg.database_url.get_secret_value())
            head = head_revision()
            checks["database"] = "ok"
            checks["schema"] = "ok" if current == head else f"pending ({current} → {head})"
            ok = ok and current == head
        except Exception as exc:
            checks["database"] = f"unavailable ({type(exc).__name__})"
            ok = False
        if redis is not None:
            try:
                await redis.ping()
                checks["redis"] = "ok"
            except Exception as exc:
                checks["redis"] = f"unavailable ({type(exc).__name__})"
                ok = False
        else:
            checks["redis"] = "not_configured"
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ready" if ok else "unavailable", "checks": checks},
        )

    return app
