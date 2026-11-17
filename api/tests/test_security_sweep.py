"""Faz 10: otomatik güvenlik taraması — uygulamadaki **her** rota dolaşılır.

Yeni bir rota eklendiğinde bu testler onu kendiliğinden kapsar:

1. Statik politika: ``/admin/v1`` altındaki her rota yönetici oturumu ister; durum değiştiren her
   yönetim rotası ya bir izin (``require_permission``) ister ya da bilinçli olarak listelenmiştir;
   herkese açık ``/v1`` rotaları açık bir listededir (yeni açık rota = bilinçli karar).
2. Anonim istek: açık olmayan her rota 401 döner.
3. Sıradan kullanıcı oturumu yönetim rotalarına giremez (ayrı çerez).
4. İzni olmayan personel: izin isteyen her rota 403 döner (SUPPORT rolüyle).
5. Enjeksiyon: tüm GET rotalarının metin parametrelerine SQL/şablon/yol enjeksiyonu girdileri
   verilir; hiçbir yanıt 5xx değildir, veritabanı ve denetim zinciri sağlam kalır.
6. Her yanıtta güvenlik başlıkları vardır.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import fastapi.routing as fr
import psycopg

from conftest import Clock, make_staff, new_client, signup_and_login, use
from mi_api import rbac

PUBLIC = {
    ("POST", "/v1/auth/register"),
    ("POST", "/v1/auth/verify-email"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/login/mfa"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/password/forgot"),
    ("POST", "/v1/auth/password/reset"),
    ("POST", "/admin/v1/auth/login"),
    ("POST", "/admin/v1/auth/logout"),
    ("GET", "/v1/football/status"),
    ("GET", "/v1/football/fixtures"),
    ("GET", "/v1/football/fixtures/{fixture_id}"),
    ("GET", "/v1/football/competitions"),
    ("GET", "/v1/football/competitions/{competition_id}/standings"),
    ("GET", "/v1/predictions/performance"),
    ("GET", "/v1/billing/plans"),
    ("POST", "/v1/billing/webhooks/{name}"),  # imzayla doğrulanır
    ("GET", "/v1/design"),
    ("GET", "/v1/notice"),
    ("GET", "/v1/content/faq"),
    ("GET", "/v1/content/pages"),
    ("GET", "/v1/content/pages/{slug}"),
    ("GET", "/metrics"),  # taşıyıcı jetonla; jeton yoksa 404
    ("GET", "/health"),
    ("GET", "/ready"),
}
# Oturum isteğe bağlı: anonim de çalışır, paket hakları backend'de uygulanır.
OPTIONAL_USER = {("GET", "/v1/predictions"), ("GET", "/v1/predictions/fixtures/{fixture_id}")}
# İzin gerektirmeyen ama durum değiştiren yönetim rotaları (yetki içeride denetlenir).
ADMIN_UNSAFE_WITHOUT_PERMISSION = {
    ("POST", "/admin/v1/auth/reauth"),  # kendi oturumunu yeniden doğrular
    ("POST", "/admin/v1/actions/ack"),  # yalnızca görebildiği uyarı
    (
        "POST",
        "/admin/v1/approvals/{approval_id}/approve",
    ),  # talebin izni + yeniden doğrulama içeride
    ("POST", "/admin/v1/approvals/{approval_id}/reject"),
    ("POST", "/admin/v1/approvals/{approval_id}/cancel"),  # yalnızca talep sahibi
    ("POST", "/admin/v1/explorer/{entity}/filters"),  # varlığın okuma izni içeride
    ("DELETE", "/admin/v1/explorer/filters/{filter_id}"),  # yalnızca kendi filtresi
}

DELIBERATE_503 = {
    "sales_closed",
    "feature_disabled",
    "licensing_not_configured",
    "provider_not_configured",
    "mfa_unavailable",
    "simulator_forbidden",
}

PAYLOADS = (
    "' OR '1'='1' --",
    '"; DROP TABLE users; --',
    "../../../../etc/passwd",
    "{{7*7}}${7*7}<script>alert(1)</script>",
    "%00\x00",
    "ü" * 600,
)


@dataclass(frozen=True)
class R:
    method: str
    path: str
    auth: frozenset[str]
    permission: str | None
    path_params: dict[str, Any]
    query_str: tuple[str, ...]


def _walk(dep: Any, out: list[Any]) -> list[Any]:
    for sub in dep.dependencies:
        out.append(sub.call)
        _walk(sub, out)
    return out


def routes(app: Any) -> Iterator[R]:
    for ctx in fr.iter_route_contexts(app.routes):
        route = getattr(ctx, "original_route", ctx)
        if not hasattr(route, "dependant"):
            continue
        calls = _walk(route.dependant, [])
        names = {getattr(c, "__name__", "") for c in calls}
        perm = None
        for c in calls:
            if getattr(c, "__qualname__", "").startswith("require_permission"):
                perm = inspect.getclosurevars(c).nonlocals["code"]
        params = {p.name: p.field_info.annotation for p in route.dependant.path_params}
        qs = tuple(
            q.name
            for q in route.dependant.query_params
            if q.field_info.annotation in (str, str | None)
        )
        for method in sorted(route.methods):
            yield R(method, getattr(ctx, "path", route.path), frozenset(names), perm, params, qs)


def fill(r: R, value: str | None = None) -> str:
    url = r.path
    for name, ann in r.path_params.items():
        if ann is int:
            v = "999999"
        elif ann is uuid.UUID:
            v = str(uuid.uuid4())
        else:
            v = value if value is not None else "yok"
        url = url.replace("{" + name + "}", v)
    return url


async def call(client: Any, r: R, url: str, **kw: Any) -> Any:
    if r.method in ("GET", "DELETE"):
        return await client.request(r.method, url, **kw)
    return await client.request(r.method, url, json={}, **kw)


SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def check_headers(resp: Any, where: str) -> None:
    for k, v in SECURITY_HEADERS.items():
        assert resp.headers.get(k) == v, f"{where}: {k} eksik/yanlış ({resp.headers.get(k)!r})"
    assert resp.headers.get("x-request-id"), where
    assert "frame-ancestors 'none'" in resp.headers.get("content-security-policy", ""), where


def test_static_route_policy(app: Any) -> None:
    all_routes = list(routes(app))
    assert len(all_routes) > 120
    keys = {(r.method, r.path) for r in all_routes}
    assert keys >= PUBLIC and keys >= OPTIONAL_USER and keys >= ADMIN_UNSAFE_WITHOUT_PERMISSION
    for r in all_routes:
        key = (r.method, r.path)
        if key in PUBLIC:
            assert not ({"current_admin", "current_user"} & r.auth), (
                f"{key} açık listede ama oturum istiyor"
            )
            continue
        if r.path.startswith("/admin/v1/"):
            assert "current_admin" in r.auth, f"{key}: yönetim rotası yönetici oturumu istemiyor"
            if r.method != "GET" and key not in ADMIN_UNSAFE_WITHOUT_PERMISSION:
                assert r.permission, f"{key}: durum değiştiren yönetim rotasında izin denetimi yok"
            if r.permission:
                assert r.permission in rbac.PERMISSIONS
        elif key in OPTIONAL_USER:
            assert "optional_user" in r.auth, key
        else:
            assert "current_user" in r.auth, f"{key}: açık listede olmayan rota oturum istemiyor"


async def test_anonymous_and_member_are_rejected_everywhere(
    app: Any, sql: psycopg.Connection[Any]
) -> None:
    checked = 0
    async with new_client(app) as anon:
        for r in routes(app):
            if (r.method, r.path) in PUBLIC | OPTIONAL_USER:
                continue
            resp = await call(anon, r, fill(r))
            assert resp.status_code == 401, (
                f"anonim {r.method} {r.path}: {resp.status_code} {resp.text[:120]}"
            )
            assert resp.json()["code"] == "unauthenticated"
            check_headers(resp, f"{r.method} {r.path}")
            checked += 1
    assert checked > 100

    # Üye oturumu (kullanıcı çerezi) yönetim API'sine geçmez.
    async with new_client(app) as member:
        await signup_and_login(member, "uye@ornek.com")
        for r in routes(app):
            if not r.path.startswith("/admin/v1/") or (r.method, r.path) in PUBLIC:
                continue
            resp = await call(member, r, fill(r))
            assert resp.status_code == 401, f"üye {r.method} {r.path}: {resp.status_code}"
    assert sql.execute("SELECT count(*) FROM user_roles").fetchone() == (0,)


async def test_staff_without_permission_gets_403_on_every_guarded_route(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    allowed = rbac.ROLE_PERMISSIONS["SUPPORT"]
    denied = 0
    before = sql.execute("SELECT count(*) FROM audit_log").fetchone()
    async with use(support.client) as s:
        for r in routes(app):
            if not r.permission or r.permission in allowed:
                continue
            resp = await call(s, r, fill(r))
            assert resp.status_code == 403, (
                f"SUPPORT {r.method} {r.path} [{r.permission}]: {resp.status_code}"
            )
            assert resp.json()["code"] == "forbidden"
            denied += 1
    assert denied > 40
    # Reddedilen isteklerin hiçbiri iz bırakan bir işlem yapmadı (yalnızca giriş kayıtları).
    after = sql.execute("SELECT count(*) FROM audit_log").fetchone()
    assert after == before


async def test_injection_inputs_never_cause_server_errors(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    root = await make_staff(app, sql, clock, "kurucu@ornek.com", "SUPER_ADMIN")
    users_before = sql.execute("SELECT count(*) FROM users").fetchone()
    tried = 0
    async with use(root.client) as a:
        for r in routes(app):
            if r.method != "GET" or r.path in ("/health", "/ready"):
                continue
            has_str_path = any(ann is str for ann in r.path_params.values())
            if not r.query_str and not has_str_path:
                continue
            for payload in PAYLOADS:
                params = dict.fromkeys(r.query_str, payload)
                resp = await a.get(fill(r, quote(payload, safe="")), params=params)
                # 503 yalnızca bilinçli "özellik kapalı / yapılandırılmamış" yanıtı olabilir.
                ok = resp.status_code < 500 or (
                    resp.status_code == 503 and resp.json().get("code") in DELIBERATE_503
                )
                assert ok, f"{r.path} {payload!r}: {resp.status_code} {resp.text[:200]}"
                check_headers(resp, r.path)
                tried += 1
        # Data Explorer filtre değerleri ve sıralama da beyaz listeden geçer.
        for payload in PAYLOADS:
            resp = await a.get(
                "/admin/v1/explorer/users",
                params={"email": payload, "sort": payload, "order": payload},
            )
            assert resp.status_code in (200, 400, 422), resp.text
    assert tried > 40
    assert sql.execute("SELECT count(*) FROM users").fetchone() == users_before
    assert sql.execute("SELECT audit_log_verify()").fetchone() == (None,)


async def test_mass_assignment_and_body_limits(app: Any, sql: psycopg.Connection[Any]) -> None:
    async with new_client(app) as c:
        r = await c.post(
            "/v1/auth/register",
            json={
                "email": "sizma@ornek.com", "password": "Guclu-Parola-2026!", "display_name": "Deneme",
                "accept_terms": True, "roles": ["SUPER_ADMIN"], "status": "active", "is_admin": True,
                "email_verified_at": "2020-01-01T00:00:00Z",
            },
        )  # fmt: skip
        assert r.status_code in (201, 202, 422), r.text
        row = sql.execute(
            "SELECT email_verified_at FROM users WHERE email='sizma@ornek.com'"
        ).fetchone()
        assert row is None or row[0] is None  # doğrulama atlatılamaz
        assert sql.execute("SELECT count(*) FROM user_roles").fetchone() == (0,)
        big = await c.post(
            "/v1/auth/login",
            content=b'{"email":"' + b"a" * 300_000 + b'"}',
            headers={"content-type": "application/json"},
        )
        assert big.status_code == 413
        deep = await c.post(
            "/v1/auth/login",
            content=b"[" * 100 + b"]" * 100,
            headers={"content-type": "application/json"},
        )
        assert deep.status_code == 400
        # NUL baytı (tarama bulgusu): gövde, sorgu ve yolda 400; önceden 500'e yol açıyordu.
        nul = await c.post("/v1/auth/login", json={"email": "a\u0000@ornek.com", "password": "x"})
        assert nul.status_code == 400
        assert (await c.get("/v1/content/pages/a%00b")).status_code == 400
        assert (await c.get("/v1/football/fixtures", params={"q": "a\x00"})).status_code == 400
        # Başka kökenden durum değiştiren istek (CSRF) reddedilir.
        evil = await c.post("/v1/auth/login", json={}, headers={"origin": "https://kotu.example"})
        assert evil.status_code == 403 and evil.json()["code"] == "origin_rejected"
