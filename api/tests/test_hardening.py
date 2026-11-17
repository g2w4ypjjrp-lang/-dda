# ruff: noqa: ASYNC230, ASYNC240
"""Faz 10: dört göz onayı, yedekleme / doğrulama / geri yükleme, Prometheus /metrics."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from conftest import (
    Clock,
    enable_mfa,
    make_settings,
    make_staff,
    new_client,
    signup_and_login,
    use,
)
from mi_api.ops import backup
from test_billing import buyer, one, set_price, sim_app, sim_order


async def _paid_order(app: Any, sql: psycopg.Connection[Any], email: str) -> int:
    async with use(await buyer(app, sql, email)) as c:
        _, token = await sim_order(c)
        r = await c.post(
            "/v1/billing/simulator/complete", json={"token": token, "outcome": "success"}
        )
        assert r.status_code == 200, r.text
    return int(one(sql, "SELECT max(id) FROM orders WHERE status = 'paid'"))


async def test_dual_control_refund_needs_second_admin(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    app = sim_app(app_factory)
    set_price(sql, "PRO", "monthly", 19900)
    number = await _paid_order(app, sql, "musteri@ornek.com")
    root = await make_staff(app, sql, clock, "kurucu@ornek.com", "SUPER_ADMIN")
    f1 = await make_staff(app, sql, clock, "finans1@ornek.com", "FINANCE_MANAGER")
    f2 = await make_staff(app, sql, clock, "finans2@ornek.com", "FINANCE_MANAGER")
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with (
        use(root.client) as r,
        use(f1.client) as a,
        use(f2.client) as b,
        use(admin.client) as ad,
    ):
        # Kural kapalıyken davranış eskisi gibi; açılınca iade onaya gider.
        assert (
            await r.put("/admin/v1/flags/dual_control", json={"enabled": True})
        ).status_code == 200
        res = await a.post(f"/admin/v1/billing/orders/{number}/refund")
        assert res.status_code == 202, res.text
        approval = res.json()["approval"]["id"]
        assert one(sql, "SELECT status FROM orders WHERE id=%s", (number,)) == "paid"
        dup = await a.post(f"/admin/v1/billing/orders/{number}/refund")
        assert dup.status_code == 409 and dup.json()["code"] == "approval_pending"

        own = await a.post(f"/admin/v1/approvals/{approval}/approve", json={"confirm": True})
        assert own.status_code == 409 and own.json()["code"] == "four_eyes"
        # İzni olmayan yönetici talebi görmez ve onaylayamaz.
        assert (await ad.get("/admin/v1/approvals")).json()["items"] == []
        assert (
            await ad.post(f"/admin/v1/approvals/{approval}/approve", json={"confirm": True})
        ).status_code == 403

        listed = (await b.get("/admin/v1/approvals")).json()
        assert listed["dual_control"] is True
        item = listed["items"][0]
        assert item["id"] == approval and item["can_decide"] and not item["mine"]
        assert item["requested_by"] == "finans1@ornek.com" and "iadesi" in item["summary"]
        keys = {i["key"] for i in (await b.get("/admin/v1/actions")).json()["items"]}
        assert f"approval:{approval}" in keys

        ok = await b.post(
            f"/admin/v1/approvals/{approval}/approve",
            json={"note": "Kontrol edildi", "confirm": True},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["status"] == "executed" and body["decided_by"] == "finans2@ornek.com"
        assert body["result"]["status"] == "refunded"
        assert one(sql, "SELECT status FROM orders WHERE id=%s", (number,)) == "refunded"
        again = await b.post(f"/admin/v1/approvals/{approval}/approve", json={"confirm": True})
        assert again.status_code == 409 and again.json()["code"] == "approval_closed"

    details = one(sql, "SELECT details FROM audit_log WHERE action='billing.refunded'")
    assert details["approval_id"] == approval
    acts = [
        x[0]
        for x in sql.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'approval.%' ORDER BY id"
        )
    ]
    assert acts == ["approval.requested", "approval.executed"]

    # Karara bağlanmış talep değiştirilemez / silinemez; onaylayan talep sahibi olamaz (CHECK).
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE approval_requests SET decision_note='x' WHERE id=%s", (approval,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("DELETE FROM approval_requests WHERE id=%s", (approval,))
    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute(
            "INSERT INTO approval_requests (action, permission, target, summary, payload, status,"
            " requested_by, requested_at, expires_at, decided_by, decided_at)"
            " SELECT 'billing.refund','finance.refund','order:0','x','{}','executed', id, now(),"
            " now() + interval '1 day', id, now() FROM users LIMIT 1"
        )


async def test_failed_execution_leaves_no_side_effects(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    app = sim_app(app_factory)
    set_price(sql, "PRO", "monthly", 19900)
    number = await _paid_order(app, sql, "musteri@ornek.com")
    f1 = await make_staff(app, sql, clock, "finans1@ornek.com", "FINANCE_MANAGER")
    f2 = await make_staff(app, sql, clock, "finans2@ornek.com", "FINANCE_MANAGER")
    sql.execute("UPDATE feature_flags SET enabled = true WHERE key = 'dual_control'")
    async with use(f1.client) as a, use(f2.client) as b:
        approval = (await a.post(f"/admin/v1/billing/orders/{number}/refund")).json()["approval"][
            "id"
        ]
        # Talep ile onay arasında durum değişti: yürütme yeniden denetler, iade yapılmaz.
        sql.execute("UPDATE orders SET status='review' WHERE id=%s", (number,))
        res = await b.post(f"/admin/v1/approvals/{approval}/approve", json={"confirm": True})
        assert res.status_code == 409 and res.json()["code"] == "not_refundable"
        assert "yürütülemedi" in res.json()["detail"]
        closed = (await b.get("/admin/v1/approvals", params={"status": "closed"})).json()["items"][
            0
        ]
        assert closed["status"] == "failed" and closed["result"]["code"] == "not_refundable"
    async with use(await buyer(app, sql, "ikinci@ornek.com")) as c:
        await sim_order(c)
    review = int(one(sql, "SELECT max(id) FROM orders"))
    sql.execute(
        "UPDATE orders SET status='review', provider_payment_id='sim_pay_x' WHERE id=%s", (review,)
    )
    f3 = await make_staff(app, sql, clock, "finans3@ornek.com", "FINANCE_MANAGER")
    f4 = await make_staff(app, sql, clock, "finans4@ornek.com", "FINANCE_MANAGER")
    async with use(f3.client) as a, use(f4.client) as b:
        # İncelemedeki sipariş kararı da onaya gider; onaylanınca abonelik verilir.
        body = {"action": "approve", "note": "Banka dekontu doğrulandı", "confirm": True}
        res = await a.post(f"/admin/v1/billing/orders/{review}/resolve", json=body)
        assert res.status_code == 202
        rid = res.json()["approval"]["id"]
        assert one(sql, "SELECT status FROM orders WHERE id=%s", (review,)) == "review"
        ok = await b.post(f"/admin/v1/approvals/{rid}/approve", json={"confirm": True})
        assert ok.status_code == 200, ok.text
    assert one(sql, "SELECT status FROM orders WHERE id=%s", (review,)) == "paid"
    assert one(sql, "SELECT count(*) FROM subscriptions WHERE order_id=%s", (review,)) == 1
    assert one(sql, "SELECT status FROM orders WHERE id=%s", (number,)) == "review"
    assert one(sql, "SELECT refund_ref FROM orders WHERE id=%s", (number,)) is None
    assert one(sql, "SELECT count(*) FROM audit_log WHERE action='billing.refunded'") == 0
    assert one(sql, "SELECT count(*) FROM audit_log WHERE action='approval.failed'") == 1
    assert one(sql, "SELECT count(*) FROM audit_log WHERE action='billing.review_approve'") == 1


async def test_dual_control_roles_reject_cancel_expire_and_switch_off(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    s1 = await make_staff(app, sql, clock, "kurucu1@ornek.com", "SUPER_ADMIN")
    s2 = await make_staff(app, sql, clock, "kurucu2@ornek.com", "SUPER_ADMIN")
    async with new_client(app) as t:
        await signup_and_login(t, "aday@ornek.com")
        await enable_mfa(t, clock)
    target = one(sql, "SELECT id FROM users WHERE email='aday@ornek.com'")
    url = f"/admin/v1/users/{target}/roles"
    roles = {"roles": ["SUPPORT"]}
    async with use(s1.client) as a, use(s2.client) as b:
        assert (
            await a.put("/admin/v1/flags/dual_control", json={"enabled": True})
        ).status_code == 200
        # Kural açıkken bile doğrulama hemen yapılır (geçersiz talep açılmaz).
        assert (await a.put(url, json={"roles": ["YOK"]})).status_code == 422
        r1 = await a.put(url, json=roles)
        assert r1.status_code == 202
        rid = r1.json()["approval"]["id"]
        assert one(sql, "SELECT count(*) FROM user_roles WHERE user_id=%s", (target,)) == 0
        assert (
            await b.post(f"/admin/v1/approvals/{rid}/reject", json={"note": "x"})
        ).status_code == 422
        rej = await b.post(f"/admin/v1/approvals/{rid}/reject", json={"note": "Gerekçe eksik"})
        assert rej.status_code == 200 and rej.json()["status"] == "rejected"

        rid2 = (await a.put(url, json=roles)).json()["approval"]["id"]
        assert (await b.post(f"/admin/v1/approvals/{rid2}/cancel")).status_code == 403
        assert (await a.post(f"/admin/v1/approvals/{rid2}/cancel")).json()["status"] == "cancelled"

        rid3 = (await a.put(url, json=roles)).json()["approval"]["id"]
        ok = await b.post(f"/admin/v1/approvals/{rid3}/approve", json={"confirm": True})
        assert ok.status_code == 200 and ok.json()["result"]["added"] == ["SUPPORT"]
        assert one(sql, "SELECT role_code FROM user_roles WHERE user_id=%s", (target,)) == "SUPPORT"

        # Kuralı kapatmak da ikinci onay ister (tek kişi kapatıp sonra tek başına iade yapamasın).
        off = await a.put("/admin/v1/flags/dual_control", json={"enabled": False})
        assert off.status_code == 202
        assert one(sql, "SELECT enabled FROM feature_flags WHERE key='dual_control'") is True
        oid = off.json()["approval"]["id"]

        # 24 saat içinde karar verilmezse talep düşer.
        rid4 = (await a.put(url, json={"roles": []})).json()["approval"]["id"]
        clock.now += timedelta(hours=25)
    s3 = await make_staff(app, sql, clock, "kurucu3@ornek.com", "SUPER_ADMIN")
    async with use(s3.client) as c:
        items = {
            i["id"]: i
            for i in (await c.get("/admin/v1/approvals", params={"status": "all"})).json()["items"]
        }
        assert items[rid4]["status"] == "expired" and items[oid]["status"] == "expired"
        assert items[rid]["status"] == "rejected" and items[rid]["decision_note"] == "Gerekçe eksik"
        assert (
            await c.post(f"/admin/v1/approvals/{rid4}/approve", json={"confirm": True})
        ).status_code == 409
    assert one(sql, "SELECT role_code FROM user_roles WHERE user_id=%s", (target,)) == "SUPPORT"
    actions = [
        x[0]
        for x in sql.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'approval.%' ORDER BY id"
        )
    ]
    assert actions.count("approval.requested") == 5
    assert {"approval.rejected", "approval.cancelled", "approval.executed"} <= set(actions)


async def test_backup_verify_prune_and_restore(
    app_factory: Any, dsn: str, sql: psycopg.Connection[Any], clock: Clock, tmp_path: Path
) -> None:
    folder = tmp_path / "yedek"
    settings = make_settings(dsn, backup_dir=str(folder), backup_keep=1)
    first = await backup.create(settings, "cli")
    assert first.status == "ok", first.detail
    v = first.detail["verify"]
    # Gerçek geri yükleme: geçici veritabanında şema sürümü, tablolar ve denetim zinciri denetlendi.
    assert v["ok"] and v["restore_tested"] and v["restore_ok"] and v["audit_chain_intact"]
    assert v["alembic_version"] == "0012" and v["tables"] > 30 and v["table_data_entries"] > 30
    file = Path(first.file or "")
    assert file.exists() and (file.stat().st_mode & 0o777) == 0o600
    assert file.with_name(file.name + ".sha256").read_text().split()[0] == first.detail["sha256"]
    leftovers = sql.execute(
        "SELECT count(*) FROM pg_database WHERE datname LIKE 'mi_verify_%%'"
    ).fetchone()
    assert leftovers == (0,)

    # Geri yükleme: ayrı bir veritabanına; çalışan veritabanı açık onay olmadan reddedilir.
    sql.execute(
        "INSERT INTO faq_items (question, answer, sort) VALUES ('Yedek sonrası?', 'Evet, sonra eklendi', 99)"
    )
    with pytest.raises(backup.BackupError, match="overwrite-current"):
        backup.restore(settings, file, dsn, overwrite_current=False)
    target = f"{sql.info.dbname}_geri"
    sql.execute(f'CREATE DATABASE "{target}"')
    try:
        target_dsn = dsn.rsplit("/", 1)[0] + f"/{target}"
        backup.restore(settings, file, target_dsn, overwrite_current=False)
        with psycopg.connect(target_dsn.replace("+psycopg", "")) as c:
            assert c.execute(
                "SELECT count(*) FROM faq_items WHERE question='Yedek sonrası?'"
            ).fetchone() == (0,)
            assert c.execute("SELECT audit_log_verify()").fetchone() == (None,)
    finally:
        sql.execute(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)')

    second = await backup.create(settings, "cli", verify_after=False)
    assert second.status == "ok" and second.detail["pruned"] == [file.name]
    assert not file.exists()
    assert one(sql, "SELECT status FROM backups WHERE id=%s", (first.id,)) == "pruned"

    # Bozulmuş dosya: özet tutmaz, doğrulama başarısız ve Action Center kritik uyarı verir.
    broken = Path(second.file or "")
    with broken.open("ab") as fh:
        fh.write(b"\0")
    res = await backup.verify(settings)
    assert res["ok"] is False and res["sha256_ok"] is False and "restore_tested" not in res
    with pytest.raises(backup.BackupError, match="SHA-256"):
        backup.restore(settings, broken, dsn.rsplit("/", 1)[0] + "/baska", overwrite_current=False)

    app = app_factory(backup_dir=str(folder), backup_keep=1)
    staff = await make_staff(app, sql, clock, "ops@ornek.com", "OPERATIONS_MANAGER")
    async with use(staff.client) as s:
        listing = (await s.get("/admin/v1/backups")).json()
        assert listing["configured"] and [i["status"] for i in listing["items"]] == ["ok", "pruned"]
        assert listing["items"][0]["verify_ok"] is False
        keys = {i["key"] for i in (await s.get("/admin/v1/actions")).json()["items"]}
        assert f"backup_verify:{second.id}" in keys
    audit_actions = {
        x[0]
        for x in sql.execute("SELECT action FROM audit_log WHERE action LIKE 'system.backup%%'")
    }
    assert audit_actions == {"system.backup_created", "system.backup_verified"}


async def test_backup_failure_and_missing_config(
    app_factory: Any, dsn: str, sql: psycopg.Connection[Any], clock: Clock, tmp_path: Path
) -> None:
    with pytest.raises(backup.BackupError):
        await backup.create(make_settings(dsn), "cli")
    bad = make_settings(dsn.rsplit("/", 1)[0] + "/olmayan_vt", backup_dir=str(tmp_path))
    # Bağlanılamayan veritabanı: kayıt da yazılamaz; hata açıkça yükselir, sahte "ok" yok.
    with pytest.raises(Exception):  # noqa: B017, PT011
        await backup.create(bad, "cli")
    assert list(tmp_path.glob("*.dump")) == [] and list(tmp_path.glob("*.part")) == []

    prod_like = app_factory(environment="test")
    staff = await make_staff(prod_like, sql, clock, "ops@ornek.com", "OPERATIONS_MANAGER")
    async with use(staff.client) as s:
        listing = (await s.get("/admin/v1/backups")).json()
        assert listing == {**listing, "configured": False, "items": []}
        keys = {i["key"] for i in (await s.get("/admin/v1/actions")).json()["items"]}
        assert "backup_unconfigured" not in keys  # yalnızca staging/production'da uyarı


async def test_prometheus_metrics_requires_token(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    closed = app_factory()
    async with new_client(closed) as c:
        assert (await c.get("/metrics")).status_code == 404
    app = app_factory(metrics_token="izleme-jetonu-0123456789")
    await app.state.metrics.record("GET", "/v1/ornek", 200, 8.0, "r1")
    async with new_client(app) as c:
        assert (await c.get("/metrics")).status_code == 401
        assert (
            await c.get("/metrics", headers={"Authorization": "Bearer yanlis"})
        ).status_code == 401
        r = await c.get("/metrics", headers={"Authorization": "Bearer izleme-jetonu-0123456789"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
        text = r.text
    assert 'mi_component_up{component="database"} 1' in text
    assert 'mi_component_configured{component="football_api"} 0' in text
    assert "mi_users 0" in text and "mi_approvals_pending 0" in text
    assert 'mi_http_requests{window="1m"}' in text and "mi_backup_configured 0" in text
    # Bilinmeyen değer uydurulmaz: kalp atışı ve yedek yokken bu ölçüler hiç yazılmaz.
    assert "mi_worker_heartbeat_age_seconds" not in text
    assert "mi_backup_last_success_timestamp_seconds" not in text
    for line in text.splitlines():
        assert line.startswith(("#", "mi_")), line
