"""Gerçek PostgreSQL üzerinde test altyapısı.

``MI_TEST_DATABASE_URL`` CREATEDB yetkili bir bağlantı olmalıdır. Oturum başında geçişler bir
şablon veritabanına bir kez uygulanır; her test bu şablondan kopyalanan temiz bir veritabanında
çalışır. ``MI_TEST_REDIS_URL`` verilirse Redis hız sınırı testleri de çalışır.
"""

from __future__ import annotations

import base64
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import psycopg
import pytest

from mi_api import security
from mi_api.app import create_app
from mi_api.config import Settings
from mi_api.migrate import upgrade

BASE_URL = os.environ.get("MI_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("MI_TEST_REDIS_URL")
TEMPLATE_DB = f"mi_tpl_{os.getpid()}"
ORIGIN = "http://localhost:3000"
KEK = base64.b64encode(b"k" * 32).decode()
PASSWORD = "Gizli-Parola-2026!"


def _with_db(url: str, dbname: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{dbname}"))


@pytest.fixture(scope="session")
def template_dsn() -> Iterator[str]:
    if not BASE_URL:
        pytest.skip("MI_TEST_DATABASE_URL tanımlı değil")
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}"')
        admin.execute(f'CREATE DATABASE "{TEMPLATE_DB}"')
    dsn = _with_db(BASE_URL, TEMPLATE_DB)
    upgrade(dsn)
    yield dsn
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}" WITH (FORCE)')


@pytest.fixture
def dsn(template_dsn: str) -> Iterator[str]:
    assert BASE_URL
    name = f"mi_t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE_DB}"')
    yield _with_db(BASE_URL, name)
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def sql(dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """Testin doğrudan veritabanı bağlantısı (kurulum ve doğrulama için)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        yield conn


@dataclass
class Clock:
    now: datetime = field(default_factory=lambda: datetime(2026, 11, 16, 12, 0, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make_settings(dsn: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": dsn,
        "session_cookie_secure": False,
        "secret_kek": KEK,
        "log_json": False,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def app_factory(dsn: str, clock: Clock) -> AsyncIterator[Any]:
    apps: list[Any] = []

    def factory(**overrides: Any) -> Any:
        app = create_app(make_settings(dsn, **overrides), clock=clock)
        apps.append(app)
        return app

    yield factory
    for app in apps:
        await app.state.services.db.close()


def new_client(app: Any, origin: str = ORIGIN) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": origin},
    )


@pytest.fixture
async def app(app_factory: Any) -> Any:
    return app_factory()


@pytest.fixture
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with new_client(app) as c:
        yield c


# --- Yardımcılar -----------------------------------------------------------------------------


def outbox_token(sql: psycopg.Connection[Any], email: str, template: str) -> str:
    row = sql.execute(
        "SELECT payload->>'link' FROM email_outbox WHERE to_address = %s AND template = %s"
        " ORDER BY id DESC LIMIT 1",
        (email, template),
    ).fetchone()
    assert row is not None, f"{email} için {template} e-postası yok"
    match = re.search(r"token=([A-Za-z0-9_-]+)", row[0])
    assert match
    return match.group(1)


async def register(
    client: httpx.AsyncClient, email: str, password: str = PASSWORD, name: str = "Test Kullanıcı"
) -> None:
    r = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": password, "display_name": name, "accept_terms": True},
    )
    assert r.status_code == 202, r.text


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/v1/auth/login", json={"email": email, "password": password})


async def signup_and_login(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    await register(client, email)
    r = await login(client, email)
    assert r.status_code == 200, r.text
    return dict(r.json()["user"])


@dataclass
class Totp:
    secret: bytes
    clock: Clock

    def code(self) -> str:
        """Güncel adımın kodu; aynı adım tekrar kullanılamadığı için saat 30 sn ilerletilir."""
        self.clock.advance(seconds=security.TOTP_STEP_S)
        return security.totp_code(self.secret, int(self.clock().timestamp()) // 30)


async def enable_mfa(client: httpx.AsyncClient, clock: Clock) -> tuple[Totp, list[str]]:
    r = await client.post("/v1/auth/mfa/setup")
    assert r.status_code == 200, r.text
    padded = r.json()["secret"] + "=" * (-len(r.json()["secret"]) % 8)
    totp = Totp(base64.b32decode(padded), clock)
    r = await client.post("/v1/auth/mfa/enable", json={"code": totp.code()})
    assert r.status_code == 200, r.text
    return totp, list(r.json()["recovery_codes"])


def grant_role(sql: psycopg.Connection[Any], email: str, role: str) -> None:
    sql.execute(
        "INSERT INTO user_roles (user_id, role_code) SELECT id, %s FROM users WHERE email = %s",
        (role, email),
    )


@dataclass
class Staff:
    email: str
    totp: Totp
    client: httpx.AsyncClient


async def make_staff(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, email: str, *roles: str
) -> Staff:
    """Kayıt + MFA + rol + yönetici girişi yapılmış istemci döner."""
    client = new_client(app)
    await signup_and_login(client, email)
    totp, _ = await enable_mfa(client, clock)
    for role in roles:
        grant_role(sql, email, role)
    r = await client.post(
        "/admin/v1/auth/login", json={"email": email, "password": PASSWORD, "code": totp.code()}
    )
    assert r.status_code == 200, r.text
    return Staff(email, totp, client)


@asynccontextmanager
async def use(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """Önceden kullanılmış (açık) istemciyi blok sonunda kapatır."""
    try:
        yield client
    finally:
        await client.aclose()
