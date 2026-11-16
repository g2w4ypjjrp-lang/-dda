"""``mi-admin`` komutları: ilk SUPER_ADMIN kurulumu ve denetim doğrulaması."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from conftest import PASSWORD, enable_mfa, make_settings, new_client
from mi_api.cli import audit_verify, bootstrap


async def test_bootstrap_super_admin_without_default_password(
    dsn: str, sql: Any, app: Any, clock: Any
) -> None:
    settings = make_settings(dsn)
    link = await bootstrap(settings, "Kurucu@Ornek.com", "Kurucu")
    token = link.split("token=")[1]
    row = sql.execute(
        "SELECT password_hash, email_verified_at FROM users WHERE email='kurucu@ornek.com'"
    ).fetchone()
    assert row[0] is None and row[1] is not None  # varsayılan parola yok

    # İkinci kurulum reddedilir.
    with pytest.raises(SystemExit):
        await bootstrap(settings, "baska@ornek.com", "Başka")

    async with new_client(app) as c:
        # Parola belirlenmeden giriş yapılamaz.
        assert (
            await c.post("/v1/auth/login", json={"email": "kurucu@ornek.com", "password": PASSWORD})
        ).status_code == 401
        r = await c.post("/v1/auth/password/reset", json={"token": token, "password": PASSWORD})
        assert r.status_code == 200
        assert (
            await c.post("/v1/auth/login", json={"email": "kurucu@ornek.com", "password": PASSWORD})
        ).status_code == 200
        totp, _ = await enable_mfa(c, clock)
        r = await c.post(
            "/admin/v1/auth/login",
            json={"email": "kurucu@ornek.com", "password": PASSWORD, "code": totp.code()},
        )
        assert r.status_code == 200 and r.json()["roles"] == ["SUPER_ADMIN"]

    assert await audit_verify(settings) is None


async def test_bootstrap_link_is_single_use(dsn: str, app: Any) -> None:
    link = await bootstrap(make_settings(dsn), "kurucu@ornek.com", "Kurucu")
    token = link.split("token=")[1]
    async with new_client(app) as c:
        ok = await c.post("/v1/auth/password/reset", json={"token": token, "password": PASSWORD})
        again = await c.post("/v1/auth/password/reset", json={"token": token, "password": PASSWORD})
        assert isinstance(ok, httpx.Response) and ok.status_code == 200 and again.status_code == 400
