"""Sağlayıcı ve senkronizasyon servisinin ayarlardan kurulması (API, işçi ve CLI ortak kullanır)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import httpx
from redis.asyncio import Redis

from mi_api.config import Settings
from mi_api.db import Database
from mi_api.football.providers.api_football import ApiFootballProvider
from mi_api.football.providers.base import FootballProvider
from mi_api.football.providers.football_data import FootballDataProvider
from mi_api.football.quota import QuotaBudget
from mi_api.football.sync import SyncService

PROVIDER_LABELS = {
    "none": "Yapılandırılmamış",
    "api_football": "API-Football (api-sports.io)",
    "football_data": "football-data.org",
    # Yalnızca geliştirme/test ortamı: ml/scripts/seed_demo.py (üretimde çalışmayı reddeder).
    "demo": "Demo verisi (test ortamı — gerçek değil)",
}


class FootballRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], datetime],
        redis: Redis | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.redis = redis
        self.transport = transport  # testlerde sahte HTTP katmanı
        self.budget: QuotaBudget | None = None
        if settings.football_provider != "none":
            self.budget = QuotaBudget(
                settings.football_provider,
                daily=settings.football_daily_budget,
                minute=settings.football_minute_budget,
                reserve_pct=settings.football_reserve_pct,
                clock=clock,
                redis=redis,
            )

    @property
    def provider_name(self) -> str:
        return self.settings.football_provider

    @property
    def configured(self) -> bool:
        return self.settings.football_provider != "none"

    def service(self, db: Database) -> tuple[SyncService, FootballProvider | None]:
        """Yeni bir sağlayıcı istemcisi ve servis döner; çağıran ``provider.aclose()`` yapmalı."""
        service = SyncService(
            db, None, provider_name=self.provider_name, budget=self.budget, clock=self.clock
        )
        provider: FootballProvider | None = None
        key = self.settings.football_api_key
        if self.configured and key is not None:
            hooks = {
                "transport": self.transport,
                "before_request": self.budget.acquire if self.budget else None,
                "on_quota": service.observe_quota,
            }
            if self.provider_name == "api_football":
                provider = ApiFootballProvider(key.get_secret_value(), **hooks)  # type: ignore[arg-type]
            else:
                provider = FootballDataProvider(key.get_secret_value(), **hooks)  # type: ignore[arg-type]
        service.provider = provider
        return service, provider
