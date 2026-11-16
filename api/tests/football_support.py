"""Futbol testleri için sahte sağlayıcı HTTP katmanı (httpx.MockTransport)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

SAMPLES = Path(__file__).parent / "samples"
QUOTA_HEADERS = {
    "x-ratelimit-requests-limit": "100",
    "x-ratelimit-requests-remaining": "87",
    "X-RateLimit-Limit": "10",
    "X-RateLimit-Remaining": "9",
}


def sample(provider: str, name: str) -> Any:
    return json.loads((SAMPLES / provider / f"{name}.json").read_text(encoding="utf-8"))


@dataclass
class FakeApi:
    """Yol + sorgu parametrelerine göre yanıt döner; eşleşmeyen istek 404 olur."""

    provider: str = "api_football"
    routes: dict[tuple[str, frozenset[tuple[str, str]]], tuple[int, Any]] = field(
        default_factory=dict
    )
    headers: dict[str, str] = field(default_factory=lambda: dict(QUOTA_HEADERS))
    calls: list[str] = field(default_factory=list)

    def add(self, path: str, params: dict[str, Any], body: Any, status: int = 200) -> None:
        if isinstance(body, str):
            body = sample(self.provider, body)
        key = (path, frozenset((k, str(v)) for k, v in params.items()))
        self.routes[key] = (status, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for prefix in ("/v4",):
            if path.startswith(prefix):
                path = path[len(prefix) :]
        params = frozenset(request.url.params.multi_items())
        self.calls.append(f"{path}?{request.url.query.decode()}")
        status, body = self.routes.get((path, params), (404, {"message": "not found"}))
        return httpx.Response(status, json=body, headers=self.headers)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def api_football_default() -> FakeApi:
    api = FakeApi("api_football")
    api.add("/fixtures", {"date": "2026-11-16", "timezone": "UTC"}, "fixtures_date")
    api.add("/fixtures", {"live": "all", "timezone": "UTC"}, "live")
    api.add("/fixtures", {"id": "1002", "timezone": "UTC"}, "fixture_1002_ft")
    api.add("/fixtures/statistics", {"fixture": "1001"}, "statistics_1001")
    api.add("/fixtures/lineups", {"fixture": "1002"}, "lineups_1002")
    api.add("/injuries", {"fixture": "1002"}, "injuries_1002")
    api.add("/standings", {"league": "9001", "season": "2026"}, "standings_9001")
    api.add("/fixtures", {"league": "9001", "season": "2026", "timezone": "UTC"}, "season_p1")
    api.add(
        "/fixtures",
        {"league": "9001", "season": "2026", "timezone": "UTC", "page": "2"},
        "season_p2",
    )
    return api
