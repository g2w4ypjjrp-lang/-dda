"""Faz 9: Data Explorer — beyaz liste, yetki, filtre doğrulama, CSV, kayıtlı filtre, global arama."""

from __future__ import annotations

import csv
import io
from typing import Any

import psycopg

from conftest import Clock, make_staff, new_client, signup_and_login, use
from mi_api.ops.explorer import ENTITIES

FORBIDDEN = ("password", "mfa_secret", "token", "digest", "pepper", "raw", "secret")


def test_whitelist_has_no_sensitive_columns() -> None:
    for e in ENTITIES.values():
        for c in e.columns:
            assert not any(word in c.key for word in FORBIDDEN), (e.key, c.key)


async def test_explorer_permissions_filters_and_related(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    async with new_client(app) as u:
        await signup_and_login(u, "ayse@ornek.com")
        await signup_and_login(
            u, "=cmd@ornek.com"
        )  # formül enjeksiyonu denemesi (e-postada izinli karakter)
    analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(analyst.client) as an, use(support.client) as s, use(admin.client) as a:
        # ANALYST: data.explore var, users.read yok → kullanıcı varlığı görünmez.
        ents = {e["key"] for e in (await an.get("/admin/v1/explorer")).json()["items"]}
        assert "fixtures" in ents and "users" not in ents and "orders" not in ents
        assert (await an.get("/admin/v1/explorer/users")).status_code == 403
        # SUPPORT: data.explore yok.
        assert (await s.get("/admin/v1/explorer")).status_code == 403
        assert (await a.get("/admin/v1/explorer/yok")).status_code == 404

        r = (await a.get("/admin/v1/explorer/users", params={"q": "AYSE"})).json()
        assert r["total"] == 1 and r["rows"][0]["email"] == "ayse@ornek.com"
        assert "password_hash" not in r["rows"][0] and "mfa_secret_enc" not in r["rows"][0]
        uid = r["rows"][0]["id"]
        rel = {x["entity"] for x in r["entity"]["related"]}
        assert {"subscriptions", "orders", "coupons"} <= rel

        r = (
            await a.get(
                "/admin/v1/explorer/users",
                params={"f.status": "active", "sort": "email", "dir": "asc", "page_size": 2},
            )
        ).json()
        assert r["total"] == 5 and len(r["rows"]) == 2 and r["rows"][0]["email"] == "=cmd@ornek.com"
        r2 = (
            await a.get(
                "/admin/v1/explorer/users",
                params={
                    "f.status": "active",
                    "sort": "email",
                    "dir": "asc",
                    "page_size": 2,
                    "page": 3,
                },
            )
        ).json()
        assert len(r2["rows"]) == 1
        for bad in (
            {"f.status": "hacker"},
            {"f.password_hash": "x"},
            {"f.id": "1 OR 1=1"},
            {"sort": "password_hash"},
        ):
            resp = await a.get("/admin/v1/explorer/users", params=bad)
            assert resp.status_code == 422, bad
        # SQL meta karakterleri aramada düz metin olarak ele alınır.
        assert (await a.get("/admin/v1/explorer/users", params={"q": "%' OR 1=1 --"})).json()[
            "total"
        ] == 0
        r = (await a.get("/admin/v1/explorer/audit", params={"f.actor_id": uid})).json()
        assert r["total"] >= 1 and all(row["actor_id"] == uid for row in r["rows"])

        # Kayıtlı filtreler kişiye özel.
        r = await a.post(
            "/admin/v1/explorer/users/filters",
            json={"name": "Aktifler", "params": {"f.status": "active", "sort": "email"}},
        )
        assert r.status_code == 201
        fid = r.json()["id"]
        assert (
            await a.post(
                "/admin/v1/explorer/users/filters",
                json={"name": "Kötü", "params": {"f.password_hash": "x"}},
            )
        ).status_code == 422
        assert [
            f["name"] for f in (await a.get("/admin/v1/explorer/users/filters")).json()["items"]
        ] == ["Aktifler"]
        assert (
            await an.delete(f"/admin/v1/explorer/filters/{fid}")
        ).status_code == 404  # başkasının filtresi
        assert (await a.delete(f"/admin/v1/explorer/filters/{fid}")).status_code == 200

        # CSV: data.export (ADMIN'de var), formül hücreleri etkisiz, denetim kaydı.
        r = await a.get(
            "/admin/v1/explorer/users/export.csv", params={"sort": "email", "dir": "asc"}
        )
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0][:2] == ["id", "email"] and "password" not in ",".join(rows[0])
        assert rows[1][1] == "'=cmd@ornek.com"
        assert (
            await an.get("/admin/v1/explorer/fixtures/export.csv")
        ).status_code == 403  # ANALYST: data.export yok

        # Global arama (Ctrl+K): yetkiye göre.
        hits = (await a.get("/admin/v1/search", params={"q": "ayse"})).json()["items"]
        assert [h["type"] for h in hits] == ["user"]
        assert (await an.get("/admin/v1/search", params={"q": "ayse"})).json()["items"] == []
    exported = sql.execute(
        "SELECT details FROM audit_log WHERE action = 'admin.data_exported'"
    ).fetchall()
    assert len(exported) == 1 and exported[0][0]["rows"] == 5
