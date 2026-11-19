"""``mi-admin`` komutları: ilk SUPER_ADMIN kurulumu ve denetim doğrulaması."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from conftest import PASSWORD, enable_mfa, make_settings, new_client
from mi_api.cli import audit_verify, bootstrap, password_link


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


async def test_password_link_for_forgotten_admin_password(
    dsn: str, sql: Any, app: Any, clock: Any
) -> None:
    """E-posta gönderimi yokken parolasını (ve telefonunu) kaybeden yönetici sunucudan bağlantı alır."""
    settings = make_settings(dsn)
    with pytest.raises(SystemExit, match="hesap yok"):
        await password_link(settings, "yok@ornek.com")
    first = (await bootstrap(settings, "kurucu@ornek.com", "Kurucu")).split("token=")[1]
    async with new_client(app) as c:
        assert (
            await c.post("/v1/auth/password/reset", json={"token": first, "password": PASSWORD})
        ).status_code == 200
        assert (
            await c.post("/v1/auth/login", json={"email": "kurucu@ornek.com", "password": PASSWORD})
        ).status_code == 200
        await enable_mfa(c, clock)

    new_password = PASSWORD + "-yeni"
    token = (await password_link(settings, " Kurucu@Ornek.com ", reset_mfa=True)).split("token=")[1]
    row = sql.execute(
        "SELECT mfa_secret_enc, mfa_enabled_at FROM users WHERE email='kurucu@ornek.com'"
    ).fetchone()
    assert row == (None, None)
    assert sql.execute(
        "SELECT count(*) FROM mfa_recovery_codes rc JOIN users u ON u.id = rc.user_id"
        " WHERE u.email='kurucu@ornek.com'"
    ).fetchone() == (0,)
    async with new_client(app) as c:
        r = await c.post("/v1/auth/password/reset", json={"token": token, "password": new_password})
        assert r.status_code == 200
        again = await c.post("/v1/auth/password/reset", json={"token": token, "password": PASSWORD})
        assert again.status_code == 400  # tek kullanım
        assert (
            await c.post("/v1/auth/login", json={"email": "kurucu@ornek.com", "password": PASSWORD})
        ).status_code == 401
        assert (
            await c.post(
                "/v1/auth/login", json={"email": "kurucu@ornek.com", "password": new_password}
            )
        ).status_code == 200
    events = [r[0] for r in sql.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert "system.password_link_issued" in events
    assert await audit_verify(settings) is None
