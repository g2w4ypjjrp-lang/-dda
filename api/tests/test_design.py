"""Faz 8: tasarım sistemleri ve Design Studio sürümleri.

* On varsayılan tasarım şemadan geçer ve yayımlanmış v1 olarak gelir; her biri farklı yerleşim seçer.
* Şema CSS'e serbest değer sokulmasını engeller (enjeksiyon denemeleri reddedilir).
* Taslak → düzenle → yayınla (hassas izin + açık onay); yayımlanan sürüm değiştirilemez (tetikleyici).
* Geri alma eski yapılandırmayı yeni sürüm olarak yayımlar; geçmiş korunur. Varsayılan değiştirilebilir.
* İzinler: CONTENT_MANAGER taslak düzenler ama yayımlayamaz.
"""

from __future__ import annotations

import copy
from typing import Any

import psycopg
import pytest
from pydantic import ValidationError

from conftest import Clock, make_staff, new_client, use
from mi_api.design.defaults import DEFAULTS, ORDER
from mi_api.design.schema import DesignConfig


def test_defaults_are_valid_and_distinct() -> None:
    assert len(ORDER) == 10 and set(ORDER) == set(DEFAULTS)
    configs = [DesignConfig.model_validate(DEFAULTS[k]) for k in ORDER]
    # Yalnızca renk teması değil: yerleşim kararları da farklı.
    assert len({c.layout.hero for c in configs}) == 10
    assert {c.layout.shell for c in configs} == {"topbar", "sidebar", "terminal", "masthead"}
    assert {c.layout.match_list for c in configs} == {"rows", "cards", "table"}
    assert {c.shape.card for c in configs} == {"flat", "outlined", "elevated", "glass", "notched"}
    assert {c.mode for c in configs} == {"dark", "light"}
    assert len({(c.typography.font, c.typography.heading_font) for c in configs}) >= 6


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("colors", "accent"), "red;} body{display:none"),
        (("colors", "bg"), "url(https://kotu.example/x.png)"),
        (("typography", "font"), "Comic Sans'; } *{"),
        (("shape", "radius"), 999),
        (("layout", "shell"), "iframe"),
        (("extra",), "x"),
    ],
)
def test_schema_rejects_css_injection_and_out_of_range(path: tuple[str, ...], value: Any) -> None:
    cfg = copy.deepcopy(DEFAULTS["signature-black"])
    target = cfg
    for p in path[:-1]:
        target = target[p]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        DesignConfig.model_validate(cfg)


async def test_public_design_endpoint(client: Any) -> None:
    r = await client.get("/v1/design")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    body = r.json()
    assert body["default"] == "signature-black" and body["order"] == list(ORDER)
    assert body["designs"]["quantum-terminal"]["config"]["layout"]["shell"] == "terminal"
    assert all(d["version"] == 1 for d in body["designs"].values())


async def test_draft_publish_rollback_and_default(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    content = await make_staff(app, sql, clock, "icerik@ornek.com", "CONTENT_MANAGER")
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(content.client) as c:
        r = await c.post(
            "/admin/v1/design/swiss-intelligence/drafts", json={"note": "Daha sıkı grid"}
        )
        assert r.status_code == 201, r.text
        draft = r.json()
        assert draft["version"] == 2 and draft["status"] == "draft"
        assert (
            await c.post("/admin/v1/design/swiss-intelligence/drafts", json={})
        ).status_code == 409
        cfg = draft["config"]
        cfg["shape"]["radius"] = 0
        cfg["colors"]["accent"] = "#a8101a"
        r = await c.put(f"/admin/v1/design/versions/{draft['id']}", json={"config": cfg})
        assert r.status_code == 200 and r.json()["config"]["colors"]["accent"] == "#a8101a"
        bad = {**cfg, "colors": {**cfg["colors"], "accent": "javascript:alert(1)"}}
        r = await c.put(f"/admin/v1/design/versions/{draft['id']}", json={"config": bad})
        assert r.status_code == 422 and r.json()["code"] == "invalid_design"
        # İçerik yöneticisi yayımlayamaz.
        r = await c.post(f"/admin/v1/design/versions/{draft['id']}/publish", json={"confirm": True})
        assert r.status_code == 403
        # Önizleme: taslak sürüm okunabilir, herkese açık uç hâlâ eski sürümü verir.
        assert (await c.get(f"/admin/v1/design/versions/{draft['id']}")).json()["status"] == "draft"
    async with new_client(app) as public:
        assert (await public.get("/v1/design")).json()["designs"]["swiss-intelligence"][
            "version"
        ] == 1

    async with use(admin.client) as a:
        assert (
            await a.post(f"/admin/v1/design/versions/{draft['id']}/publish", json={})
        ).status_code == 422
        r = await a.post(f"/admin/v1/design/versions/{draft['id']}/publish", json={"confirm": True})
        assert r.status_code == 200 and r.json()["status"] == "published"
        hist = (await a.get("/admin/v1/design/swiss-intelligence/versions")).json()["items"]
        assert [(h["version"], h["status"]) for h in hist] == [(2, "published"), (1, "archived")]
        # Yayımlanmış sürüm değiştirilemez (API ve veritabanı).
        r = await a.put(f"/admin/v1/design/versions/{draft['id']}", json={"config": cfg})
        assert r.status_code == 409
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql.execute("UPDATE design_versions SET config = '{}' WHERE id = %s", (draft["id"],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql.execute("DELETE FROM design_versions WHERE id = %s", (draft["id"],))

        # Geri alma: v1 yapılandırması v3 olarak yayımlanır; v2 arşivlenir.
        v1 = hist[1]["id"]
        r = await a.post(f"/admin/v1/design/versions/{v1}/rollback", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 3 and r.json()["config"] == hist[1]["config"]
        hist = (await a.get("/admin/v1/design/swiss-intelligence/versions")).json()["items"]
        assert [(h["version"], h["status"]) for h in hist] == [
            (3, "published"),
            (2, "archived"),
            (1, "archived"),
        ]
        assert (
            await a.post(
                f"/admin/v1/design/versions/{hist[0]['id']}/rollback", json={"confirm": True}
            )
        ).status_code == 409

        # Taslak atma.
        d = (await a.post("/admin/v1/design/editorial-sports/drafts", json={})).json()
        assert (await a.post(f"/admin/v1/design/versions/{d['id']}/discard")).json()[
            "status"
        ] == "discarded"

        # Varsayılan tasarım.
        r = await a.put(
            "/admin/v1/design/default", json={"design_key": "quantum-terminal", "confirm": True}
        )
        assert r.status_code == 200
        assert (
            await a.put("/admin/v1/design/default", json={"design_key": "yok", "confirm": True})
        ).status_code == 404
        listed = (await a.get("/admin/v1/design")).json()
        assert listed["default"] == "quantum-terminal" and len(listed["items"]) == 10
    async with new_client(app) as public:
        body = (await public.get("/v1/design")).json()
        assert body["default"] == "quantum-terminal"
        assert body["designs"]["swiss-intelligence"]["version"] == 3
    actions = [
        r[0]
        for r in sql.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'design.%' ORDER BY id"
        )
    ]
    assert actions == [
        "design.draft_created", "design.draft_updated", "design.published", "design.rolled_back",
        "design.draft_created", "design.draft_discarded", "design.default_changed",
    ]  # fmt: skip


async def test_design_publish_requires_fresh_reauth(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(admin.client) as a:
        d = (await a.post("/admin/v1/design/ai-atelier/drafts", json={})).json()
        clock.advance(minutes=6)
        r = await a.post(f"/admin/v1/design/versions/{d['id']}/publish", json={"confirm": True})
        assert r.status_code == 403 and r.json()["code"] == "reauth_required"
        support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
        async with use(support.client) as s:
            assert (await s.get("/admin/v1/design")).status_code == 403


def test_defaults_meet_wcag_aa_contrast() -> None:
    """Faz 10 axe bulgusu: her metin rengi her yüzeyde ve rozet zemininde en az 4,5:1."""
    from mi_api.design import contrast

    for key in ORDER:
        assert contrast.issues(DEFAULTS[key]["colors"]) == [], key
    assert round(contrast.ratio("#000000", "#ffffff"), 1) == 21.0
    assert contrast.mix("#ff0000", "#ffffff", 0.15) == "#ffd9d9"


async def test_low_contrast_design_cannot_be_published_or_restored(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(admin.client) as a:
        draft = (await a.post("/admin/v1/design/swiss-intelligence/drafts", json={})).json()
        assert draft["contrast_issues"] == []
        cfg = copy.deepcopy(draft["config"])
        cfg["colors"]["muted"] = "#c8c8c8"  # açık zeminde soluk gri: ~1,6:1
        r = await a.put(f"/admin/v1/design/versions/{draft['id']}", json={"config": cfg})
        assert r.status_code == 200  # taslak kaydedilir, uyarı görünür
        issues = r.json()["contrast_issues"]
        assert issues and {i["foreground"] for i in issues} == {"muted"}
        assert "en az 4.5:1" in issues[0]["message"]
        r = await a.post(f"/admin/v1/design/versions/{draft['id']}/publish", json={"confirm": True})
        assert r.status_code == 422 and r.json()["code"] == "contrast_insufficient"
        assert sql.execute(
            "SELECT status FROM design_versions WHERE id = %s", (draft["id"],)
        ).fetchone() == ("draft",)
        await a.post(f"/admin/v1/design/versions/{draft['id']}/discard")

        # Eşiğin altındaki eski (arşivlenmiş) bir sürüme geri dönülemez.
        old = copy.deepcopy(draft["config"])
        old["colors"]["muted"] = "#c8c8c8"
        row = sql.execute(
            "INSERT INTO design_versions (design_key, version, status, config, published_at)"
            " VALUES ('swiss-intelligence', 99, 'archived', %s, now()) RETURNING id",
            (psycopg.types.json.Jsonb(old),),
        ).fetchone()
        assert row is not None
        r = await a.post(f"/admin/v1/design/versions/{row[0]}/rollback", json={"confirm": True})
        assert r.status_code == 422 and r.json()["code"] == "contrast_insufficient"
