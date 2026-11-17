"""Sistem uç noktaları ve istek koruması."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from conftest import new_client


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert len(r.headers["x-request-id"]) >= 8


async def test_request_id_propagated(client: httpx.AsyncClient) -> None:
    r = await client.get("/health", headers={"X-Request-ID": "istek-12345678"})
    assert r.headers["x-request-id"] == "istek-12345678"
    r = await client.get("/health", headers={"X-Request-ID": "<script>"})
    assert r.headers["x-request-id"] != "<script>"


async def test_ready(client: httpx.AsyncClient) -> None:
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"] == {"database": "ok", "schema": "ok", "redis": "not_configured"}


async def test_ready_detects_pending_migrations(
    client: httpx.AsyncClient, sql: psycopg.Connection[Any]
) -> None:
    sql.execute("UPDATE alembic_version SET version_num = '0000'")
    r = await client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["schema"].startswith("pending")


async def test_ready_reports_database_down(app_factory: Any) -> None:
    app = app_factory(database_url="postgresql://nobody:x@127.0.0.1:1/none")
    async with new_client(app) as c:
        r = await c.get("/ready")
        assert r.status_code == 503 and r.json()["checks"]["database"].startswith("unavailable")


async def test_body_limits(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/auth/login",
        content=b"{" + b" " * 300_000 + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413 and r.json()["code"] == "body_too_large"
    r = await client.post(
        "/v1/auth/login",
        content=b"[" * 100 + b"]" * 100,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    r = await client.post(
        "/v1/auth/login", content=b'{"email": "\xff"}', headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400


async def test_validation_error_shape(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/auth/login", json={"email": "gecersiz"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error" and body["fields"]


async def test_openapi_available_outside_production(app_factory: Any) -> None:
    async with new_client(app_factory()) as c:
        assert (await c.get("/openapi.json")).status_code == 200
