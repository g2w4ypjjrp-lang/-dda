"""Faz 7: favoriler, panel düzeni, bildirimler (tercih, güvenlik, abonelik, kupon, tarama, duyuru), içerik."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import psycopg

from conftest import ORIGIN, PASSWORD, Clock, make_staff, member, new_client, signup_and_login, use
from mi_api.engage.scan import scan


def client_from(app: Any, ip: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 5000)),
        base_url="http://testserver",
        headers={"Origin": ORIGIN},
    )


async def notes(c: httpx.AsyncClient) -> list[dict[str, Any]]:
    return list((await c.get("/v1/notifications")).json()["items"])


async def test_favorites_and_dashboard_layout(
    app: Any, seeded: dict[str, Any], sql: psycopg.Connection[Any]
) -> None:
    team = sql.execute(
        "SELECT home_team_id FROM football_fixtures WHERE id=%s", (seeded["fixtures"][0],)
    ).fetchone()[0]
    async with new_client(app) as c:
        await signup_and_login(c, "fan@ornek.com")
        for _ in range(2):  # tekrar eklemek çoğaltmaz
            assert (
                await c.post("/v1/favorites", json={"kind": "team", "ref_id": team})
            ).status_code == 201
        assert (
            await c.post("/v1/favorites", json={"kind": "fixture", "ref_id": seeded["fixtures"][1]})
        ).status_code == 201
        assert (
            await c.post("/v1/favorites", json={"kind": "team", "ref_id": 999999})
        ).status_code == 404
        fav = (await c.get("/v1/favorites")).json()
        assert [t["id"] for t in fav["teams"]] == [team] and fav["fixtures"] == [
            seeded["fixtures"][1]
        ]
        assert (await c.delete(f"/v1/favorites/team/{team}")).json()["favorite"] is False
        assert (await c.get("/v1/favorites")).json()["teams"] == []

        d = (await c.get("/v1/dashboard/layout")).json()
        assert d["custom"] is False and len(d["layout"]) >= 8 and "favorite_teams" in d["widgets"]
        layout = [{"widget": "today", "size": "l"}, {"widget": "virtual", "size": "s"}]
        r = await c.put("/v1/dashboard/layout", json={"layout": layout})
        assert (
            r.status_code == 200
            and (await c.get("/v1/dashboard/layout")).json()["layout"] == layout
        )
        for bad in (
            [{"widget": "hack", "size": "s"}],
            [{"widget": "today", "size": "l"}, {"widget": "today", "size": "s"}],
            [{"widget": "today", "size": "xl"}],
        ):
            assert (await c.put("/v1/dashboard/layout", json={"layout": bad})).status_code == 422
        assert (await c.delete("/v1/dashboard/layout")).json()["custom"] is False
        acts = (await c.get("/v1/me/activity")).json()["items"]
        assert acts[0]["label"] == "Giriş yapıldı"


async def test_security_notifications_and_prefs(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "guvenli@ornek.com")
        assert await notes(c) == []  # ilk giriş uyarı üretmez
    sql.execute("UPDATE users SET email_verified_at = now() WHERE email = 'guvenli@ornek.com'")
    async with client_from(app, "203.0.113.9") as other:
        assert (
            await other.post(
                "/v1/auth/login", json={"email": "guvenli@ornek.com", "password": PASSWORD}
            )
        ).status_code == 200
        items = await notes(other)
        assert items[0]["category"] == "security" and "203.0.113.9" in items[0]["body"]
        # Güvenlik bildirimi uygulama içinde kapatılamaz; e-posta varsayılan açık → kuyrukta bekler (M-G6).
        r = (
            await other.put(
                "/v1/notifications/prefs",
                json={"prefs": {"security": {"in_app": False}, "subscription": {"in_app": False}}},
            )
        ).json()
        p = {x["category"]: x for x in r["items"]}
        assert (
            p["security"]["in_app"] is True
            and p["security"]["locked_in_app"]
            and p["subscription"]["in_app"] is False
        )
        assert (
            await other.put("/v1/notifications/prefs", json={"prefs": {"yok": {"email": True}}})
        ).status_code == 422
        clock.advance(seconds=5)
        r = await other.post(
            "/v1/auth/password/change",
            json={"current_password": PASSWORD, "new_password": "Yeni-Guclu-Parola-2027!"},
        )
        assert r.status_code == 200, r.text
        items = await notes(other)
        assert items[0]["title"] == "Parolanız değiştirildi"
        assert (await other.get("/v1/notifications")).json()["unread"] == 2
        assert (await other.post("/v1/notifications/read", json={"ids": [items[0]["id"]]})).json()[
            "updated"
        ] == 1
        assert (await other.post("/v1/notifications/read", json={"all": True})).json()[
            "updated"
        ] == 1
        assert (await other.get("/v1/notifications", params={"unread": True})).json()["items"] == []
    outbox = sql.execute(
        "SELECT template, status FROM email_outbox WHERE template LIKE 'notify_%' ORDER BY id"
    ).fetchall()
    assert outbox == [("notify_security", "pending"), ("notify_security", "pending")]


async def test_subscription_coupon_scan_and_broadcast(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    fx = seeded["fixtures"]
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with new_client(app) as c:
        await member(c, sql, "taraftar@ornek.com", plan="PRO")
        await c.post("/v1/notifications/prefs", json={})
        async with use(admin.client) as a:
            r = await a.post(
                "/admin/v1/billing/subscriptions/grant",
                json={"email": "taraftar@ornek.com", "plan": "ELITE", "days": 2},
            )
            assert r.status_code == 201
        items = await notes(c)
        assert (
            items[0]["category"] == "subscription" and items[0]["title"] == "ELITE paketiniz etkin"
        )

        # Kupon sonuçlanınca bildirim.
        r = await c.post(
            "/v1/coupons",
            json={"legs": [{"prediction_id": seeded["preds"][0], "market": "1x2", "pick": "home"}]},
        )
        assert r.status_code == 201
        home = sql.execute(
            "SELECT home_team_id FROM football_fixtures WHERE id=%s", (fx[1],)
        ).fetchone()[0]
        await c.post("/v1/favorites", json={"kind": "team", "ref_id": home})
    sql.execute(
        "UPDATE football_fixtures SET status='finished', status_detail='FT', home_goals=2, away_goals=0, ft_home=2, ft_away=0 WHERE id=%s",
        (fx[0],),
    )
    analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
    async with use(analyst.client) as an:
        assert (await an.post("/admin/v1/coupons/settle")).json()["coupons"] == 1

    # Tarama: favori takımın maçı 60 dk içinde; ELITE 2 gün içinde bitiyor.
    clock.now = sql.execute(
        "SELECT kickoff_at FROM football_fixtures WHERE id=%s", (fx[1],)
    ).fetchone()[0] - timedelta(minutes=30)
    async with app.state.services.db.session() as session:
        first = await scan(session, clock())
    async with app.state.services.db.session() as session:
        again = await scan(session, clock())
    assert (
        first["match"] == 1
        and first["subscription"] == 1
        and again == {"match": 0, "result": 0, "subscription": 0}
    )
    sql.execute(
        "UPDATE football_fixtures SET status='finished', status_detail='FT', home_goals=1, away_goals=1, ft_home=1, ft_away=1 WHERE id=%s",
        (fx[1],),
    )
    clock.advance(hours=3)
    async with app.state.services.db.session() as session:
        assert (await scan(session, clock()))["result"] == 1
    cats = [
        r[0]
        for r in sql.execute(
            "SELECT n.category FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.email='taraftar@ornek.com' ORDER BY n.id"
        )
    ]
    assert cats == ["subscription", "coupon", "match", "subscription", "result"]

    # Duyuru: CONTENT_MANAGER; sistem bildirimini kapatan almaz.
    sql.execute(
        "INSERT INTO notification_prefs (user_id, category, in_app, email) SELECT id, 'system', false, false FROM users WHERE email='analist@ornek.com'"
    )
    cm = await make_staff(app, sql, clock, "icerik@ornek.com", "CONTENT_MANAGER")
    async with use(cm.client) as m:
        r = await m.post(
            "/admin/v1/notifications/broadcast",
            json={
                "title": "Yeni özellik",
                "body": "İlk yarı piyasaları geldi.",
                "link": "/maclar",
                "confirm": True,
            },
        )
        assert r.status_code == 200
        recipients = r.json()["recipients"]
        assert (
            await m.post(
                "/admin/v1/notifications/broadcast",
                json={"title": "x", "body": "y", "link": "javascript:alert(1)", "confirm": True},
            )
        ).status_code == 422
    total_active = sql.execute("SELECT count(*) FROM users WHERE status='active'").fetchone()[0]
    assert recipients == total_active - 1
    assert (
        sql.execute(
            "SELECT count(*) FROM audit_log WHERE action='notifications.broadcast'"
        ).fetchone()[0]
        == 1
    )


async def test_content_management(app: Any, sql: psycopg.Connection[Any], clock: Clock) -> None:
    async with new_client(app) as public:
        faq = (await public.get("/v1/content/faq")).json()["items"]
        assert len(faq) == 5
        page = (await public.get("/v1/content/pages/kullanim-kosullari")).json()
        assert (
            page["published"] is False and page["body"] is None and "hukuki" in page["pending_note"]
        )
        assert (await public.get("/v1/content/pages/yok")).status_code == 404
    cm = await make_staff(app, sql, clock, "icerik@ornek.com", "CONTENT_MANAGER")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with use(cm.client) as m, use(support.client) as s:
        assert (await s.get("/admin/v1/content")).status_code == 403
        body = {"title": "Kullanım Koşulları", "body": "kısa", "published": True}
        assert (
            await m.put("/admin/v1/content/pages/kullanim-kosullari", json=body)
        ).status_code == 422
        body["body"] = "Bu metin hukuk onayından geçmiş kullanım koşullarıdır. " * 3
        r = await m.put("/admin/v1/content/pages/kullanim-kosullari", json=body)
        assert r.status_code == 200 and r.json()["published_at"]
        f = (
            await m.post(
                "/admin/v1/content/faq",
                json={
                    "question": "Mobil uygulama var mı?",
                    "answer": "Site telefona uygulama olarak eklenebilir.",
                    "sort": 9,
                },
            )
        ).json()
        assert (
            await m.put(
                f"/admin/v1/content/faq/{f['id']}",
                json={
                    "question": "Mobil uygulama var mı?",
                    "answer": "Evet, PWA olarak eklenebilir.",
                    "sort": 9,
                    "published": False,
                },
            )
        ).status_code == 200
    async with new_client(app) as public:
        page = (await public.get("/v1/content/pages/kullanim-kosullari")).json()
        assert page["body"].startswith("Bu metin")
        assert (
            len((await public.get("/v1/content/faq")).json()["items"]) == 5
        )  # yayımlanmamış soru görünmez
    assert (
        sql.execute("SELECT count(*) FROM audit_log WHERE action LIKE 'content.%'").fetchone()[0]
        == 3
    )
