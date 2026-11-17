# ruff: noqa: E501
"""Kullanıcı etkileşimi API'si (Faz 7).

Kullanıcı: bildirimler (liste, okundu, tercihler), favoriler (takım, lig, maç), panel düzeni
(widget'lar), son etkinlikler. Herkese açık: SSS ve yayımlanmış içerik sayfaları.
Yönetim: içerik ve SSS düzenleme (``content.manage``), sistem duyurusu (``notifications.manage``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from mi_api import audit
from mi_api.context import (
    DbDep,
    MetaDep,
    Principal,
    ServicesDep,
    UserDep,
    enforce_limit,
    require_permission,
)
from mi_api.engage.models import (
    ContentPage,
    DashboardLayout,
    FaqItem,
    Favorite,
    Notification,
    NotificationPref,
)
from mi_api.engage.notify import CATEGORIES, LABELS, prefs_for
from mi_api.errors import ApiError
from mi_api.football.models import Competition, Fixture, Team
from mi_api.models import AuditLog, User

WIDGETS = {
    "account": "Hesap özeti",
    "subscription": "Abonelik durumu",
    "today": "Günün maçları",
    "featured": "Öne çıkan analizler",
    "favorite_teams": "Favori takımlar",
    "favorite_leagues": "Favori ligler",
    "saved_matches": "Kaydedilmiş maçlar",
    "coupons": "Kupon geçmişi",
    "virtual": "Sanal bakiye ve simülasyon",
    "notifications": "Bildirimler",
    "activity": "Son aktiviteler",
}
DEFAULT_LAYOUT = [
    {"widget": "account", "size": "s"},
    {"widget": "subscription", "size": "s"},
    {"widget": "virtual", "size": "s"},
    {"widget": "today", "size": "l"},
    {"widget": "featured", "size": "m"},
    {"widget": "favorite_teams", "size": "m"},
    {"widget": "saved_matches", "size": "m"},
    {"widget": "coupons", "size": "m"},
    {"widget": "notifications", "size": "m"},
    {"widget": "activity", "size": "m"},
]
ACTIVITY_LABELS = {
    "auth.login": "Giriş yapıldı",
    "auth.logout": "Çıkış yapıldı",
    "auth.password_changed": "Parola değiştirildi",
    "auth.mfa_enabled": "İki adımlı doğrulama açıldı",
    "auth.mfa_disabled": "İki adımlı doğrulama kapatıldı",
    "coupon.created": "Kupon kaydedildi",
    "virtual.account_opened": "Sanal portföy açıldı",
    "virtual.settings_changed": "Sanal portföy ayarları değişti",
    "billing.checkout_started": "Satın alma başlatıldı",
    "billing.license_redeemed": "Lisans kullanıldı",
    "user.email_verified": "E-posta doğrulandı",
}


class ReadBody(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=200)
    all: bool = False


class PrefBody(BaseModel):
    prefs: dict[str, dict[Literal["in_app", "email"], bool]]


class FavoriteBody(BaseModel):
    kind: Literal["team", "competition", "fixture"]
    ref_id: int = Field(ge=1)


class Widget(BaseModel):
    widget: str = Field(max_length=32)
    size: Literal["s", "m", "l"]


class LayoutBody(BaseModel):
    layout: list[Widget] = Field(max_length=len(WIDGETS))


class PageBody(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(max_length=60000)
    published: bool


class FaqBody(BaseModel):
    question: str = Field(min_length=5, max_length=200)
    answer: str = Field(min_length=5, max_length=2000)
    sort: int = Field(default=0, ge=0, le=1000)
    published: bool = True


class BroadcastBody(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=600)
    link: str | None = Field(default=None, pattern=r"^/[A-Za-z0-9/_?=&.%-]*$", max_length=200)
    confirm: Literal[True]


def notification_view(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "category": n.category,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "created_at": n.created_at.isoformat(),
        "read": n.read_at is not None,
    }


def page_view(p: ContentPage, full: bool = True) -> dict[str, Any]:
    out = {
        "slug": p.slug,
        "title": p.title,
        "kind": p.kind,
        "published": p.published,
        "updated_at": p.updated_at.isoformat(),
        "published_at": p.published_at.isoformat() if p.published_at else None,
    }
    if full:
        out["body"] = p.body
    return out


def faq_view(f: FaqItem) -> dict[str, Any]:
    return {
        "id": f.id,
        "question": f.question,
        "answer": f.answer,
        "sort": f.sort,
        "published": f.published,
    }


def _perm(code: str) -> Any:
    return Depends(require_permission(code))


def create_engage_router() -> APIRouter:
    router = APIRouter(tags=["engage"])

    # --- Bildirimler -----------------------------------------------------------------------

    @router.get("/v1/notifications")
    async def list_notifications(
        user: UserDep,
        db: DbDep,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
        unread: bool = False,
    ) -> dict[str, Any]:
        stmt = select(Notification).where(Notification.user_id == user.user.id)
        if unread:
            stmt = stmt.where(Notification.read_at.is_(None))
        rows = (
            await db.execute(
                stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
            )
        ).scalars()
        count = (
            await db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user.user.id, Notification.read_at.is_(None))
            )
        ).scalar_one()
        return {"items": [notification_view(n) for n in rows], "unread": count}

    @router.post("/v1/notifications/read")
    async def mark_read(
        body: ReadBody, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        stmt = update(Notification).where(
            Notification.user_id == user.user.id, Notification.read_at.is_(None)
        )
        if not body.all:
            if not body.ids:
                raise ApiError(422, "nothing_selected", "Bildirim seçilmedi")
            stmt = stmt.where(Notification.id.in_(body.ids))
        result = await db.execute(stmt.values(read_at=services.clock()))
        return {"updated": result.rowcount}  # type: ignore[attr-defined]

    @router.get("/v1/notifications/prefs")
    async def get_prefs(user: UserDep, db: DbDep) -> dict[str, Any]:
        prefs = await prefs_for(db, user.user.id)
        return {
            "items": [
                {"category": c, "label": LABELS[c], **prefs[c], "locked_in_app": c == "security"}
                for c in CATEGORIES
            ],
            "email_note": "E-posta gönderimi, e-posta sağlayıcısı bağlandığında başlar (M-G6); o zamana kadar iletiler kuyrukta bekler.",
        }

    @router.put("/v1/notifications/prefs")
    async def put_prefs(body: PrefBody, user: UserDep, db: DbDep) -> dict[str, Any]:
        current = await prefs_for(db, user.user.id)
        for cat, values in body.prefs.items():
            if cat not in CATEGORIES:
                raise ApiError(422, "unknown_category", f"Bilinmeyen kategori: {cat}")
            merged: dict[str, bool] = {**current[cat], **{str(k): v for k, v in values.items()}}
            if cat == "security":
                merged["in_app"] = True  # güvenlik bildirimleri kapatılamaz
            stmt = (
                insert(NotificationPref)
                .values(
                    user_id=user.user.id,
                    category=cat,
                    in_app=merged["in_app"],
                    email=merged["email"],
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "category"],
                    set_={"in_app": merged["in_app"], "email": merged["email"]},
                )
            )
            await db.execute(stmt)
        return await get_prefs(user, db)

    # --- Favoriler -------------------------------------------------------------------------

    @router.get("/v1/favorites")
    async def favorites(user: UserDep, db: DbDep) -> dict[str, Any]:
        rows = (
            (
                await db.execute(
                    select(Favorite)
                    .where(Favorite.user_id == user.user.id)
                    .order_by(Favorite.created_at)
                )
            )
            .scalars()
            .all()
        )
        ids = {
            k: [f.ref_id for f in rows if f.kind == k] for k in ("team", "competition", "fixture")
        }
        teams = (
            {
                t.id: t
                for t in (await db.execute(select(Team).where(Team.id.in_(ids["team"])))).scalars()
            }
            if ids["team"]
            else {}
        )
        comps = (
            {
                c.id: c
                for c in (
                    await db.execute(
                        select(Competition).where(Competition.id.in_(ids["competition"]))
                    )
                ).scalars()
            }
            if ids["competition"]
            else {}
        )
        fixtures = (
            {
                f.id: f
                for f in (
                    await db.execute(select(Fixture).where(Fixture.id.in_(ids["fixture"])))
                ).scalars()
            }
            if ids["fixture"]
            else {}
        )
        return {
            "teams": [
                {"id": i, "name": teams[i].name, "logo_url": teams[i].logo_url}
                for i in ids["team"]
                if i in teams
            ],
            "competitions": [
                {"id": i, "name": comps[i].name, "logo_url": comps[i].logo_url}
                for i in ids["competition"]
                if i in comps
            ],
            "fixtures": [i for i in ids["fixture"] if i in fixtures],
        }

    @router.post("/v1/favorites", status_code=201)
    async def add_favorite(
        body: FavoriteBody, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"favorites:user:{user.user.id}", 120, 600)
        model = {"team": Team, "competition": Competition, "fixture": Fixture}[body.kind]
        if await db.get(model, body.ref_id) is None:
            raise ApiError(404, "not_found", "Kayıt bulunamadı")
        count = (
            await db.execute(
                select(func.count()).select_from(Favorite).where(Favorite.user_id == user.user.id)
            )
        ).scalar_one()
        if count >= 200:
            raise ApiError(422, "too_many", "En fazla 200 favori eklenebilir")
        await db.execute(
            insert(Favorite)
            .values(
                user_id=user.user.id,
                kind=body.kind,
                ref_id=body.ref_id,
                created_at=services.clock(),
            )
            .on_conflict_do_nothing()
        )
        return {"kind": body.kind, "ref_id": body.ref_id, "favorite": True}

    @router.get("/v1/favorites/fixtures")
    async def favorite_fixtures(
        user: UserDep,
        db: DbDep,
        services: ServicesDep,
        days: Annotated[int, Query(ge=1, le=14)] = 7,
    ) -> dict[str, Any]:
        """Favori takım/lig maçları ve kaydedilmiş maçlar: dün ile ``days`` gün sonrası arası."""
        from mi_api.football.api import _fixture_query, fixture_view

        favs = (
            (await db.execute(select(Favorite).where(Favorite.user_id == user.user.id)))
            .scalars()
            .all()
        )
        teams = [f.ref_id for f in favs if f.kind == "team"]
        comps = [f.ref_id for f in favs if f.kind == "competition"]
        saved = [f.ref_id for f in favs if f.kind == "fixture"]
        now = services.clock()
        out: dict[str, list[dict[str, Any]]] = {"teams": [], "competitions": [], "saved": []}
        window = (
            Fixture.kickoff_at >= now - timedelta(days=1),
            Fixture.kickoff_at <= now + timedelta(days=days),
        )
        if teams:
            rows = (
                await db.execute(
                    _fixture_query()
                    .where(
                        or_(Fixture.home_team_id.in_(teams), Fixture.away_team_id.in_(teams)),
                        *window,
                    )
                    .order_by(Fixture.kickoff_at)
                    .limit(30)
                )
            ).all()
            out["teams"] = [fixture_view(fx, h, a, c, se, now) for fx, h, a, c, se in rows]
        if comps:
            rows = (
                await db.execute(
                    _fixture_query()
                    .where(Competition.id.in_(comps), *window)
                    .order_by(Fixture.kickoff_at)
                    .limit(30)
                )
            ).all()
            out["competitions"] = [fixture_view(fx, h, a, c, se, now) for fx, h, a, c, se in rows]
        if saved:
            rows = (
                await db.execute(
                    _fixture_query()
                    .where(Fixture.id.in_(saved))
                    .order_by(Fixture.kickoff_at.desc())
                    .limit(30)
                )
            ).all()
            out["saved"] = [fixture_view(fx, h, a, c, se, now) for fx, h, a, c, se in rows]
        return out

    @router.delete("/v1/favorites/{kind}/{ref_id}")
    async def remove_favorite(
        kind: Literal["team", "competition", "fixture"], ref_id: int, user: UserDep, db: DbDep
    ) -> dict[str, Any]:
        fav = await db.get(Favorite, (user.user.id, kind, ref_id))
        if fav is not None:
            await db.delete(fav)
        return {"kind": kind, "ref_id": ref_id, "favorite": False}

    # --- Panel düzeni ve etkinlik ----------------------------------------------------------

    @router.get("/v1/dashboard/layout")
    async def get_layout(user: UserDep, db: DbDep) -> dict[str, Any]:
        row = await db.get(DashboardLayout, user.user.id)
        return {
            "layout": row.layout if row else DEFAULT_LAYOUT,
            "custom": row is not None,
            "widgets": WIDGETS,
        }

    @router.put("/v1/dashboard/layout")
    async def put_layout(
        body: LayoutBody, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        seen: set[str] = set()
        for w in body.layout:
            if w.widget not in WIDGETS:
                raise ApiError(422, "unknown_widget", f"Bilinmeyen bileşen: {w.widget}")
            if w.widget in seen:
                raise ApiError(422, "duplicate_widget", "Bir bileşen panelde bir kez bulunabilir")
            seen.add(w.widget)
        layout = [w.model_dump() for w in body.layout]
        await db.execute(
            insert(DashboardLayout).values(user_id=user.user.id, layout=layout, updated_at=services.clock())
            .on_conflict_do_update(index_elements=["user_id"], set_={"layout": layout, "updated_at": services.clock()})
        )  # fmt: skip
        return {"layout": layout, "custom": True, "widgets": WIDGETS}

    @router.delete("/v1/dashboard/layout")
    async def reset_layout(user: UserDep, db: DbDep) -> dict[str, Any]:
        row = await db.get(DashboardLayout, user.user.id)
        if row is not None:
            await db.delete(row)
        return {"layout": DEFAULT_LAYOUT, "custom": False, "widgets": WIDGETS}

    @router.get("/v1/me/activity")
    async def activity(
        user: UserDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=50)] = 15
    ) -> dict[str, Any]:
        rows = (
            await db.execute(
                select(AuditLog.occurred_at, AuditLog.action, AuditLog.ip)
                .where(
                    AuditLog.actor_type == "user",
                    AuditLog.actor_id == str(user.user.id),
                    AuditLog.action.in_(tuple(ACTIVITY_LABELS)),
                )
                .order_by(AuditLog.id.desc())
                .limit(limit)
            )
        ).all()
        return {
            "items": [
                {
                    "at": at.isoformat(),
                    "action": a,
                    "label": ACTIVITY_LABELS[a],
                    "ip": str(ip) if ip else None,
                }
                for at, a, ip in rows
            ]
        }

    # --- İçerik (herkese açık) -------------------------------------------------------------

    @router.get("/v1/content/faq")
    async def faq(db: DbDep) -> dict[str, Any]:
        rows = (
            await db.execute(
                select(FaqItem).where(FaqItem.published).order_by(FaqItem.sort, FaqItem.id)
            )
        ).scalars()
        return {"items": [{"id": f.id, "question": f.question, "answer": f.answer} for f in rows]}

    @router.get("/v1/content/pages")
    async def pages(db: DbDep) -> dict[str, Any]:
        rows = (
            await db.execute(select(ContentPage).order_by(ContentPage.kind, ContentPage.title))
        ).scalars()
        return {
            "items": [
                {"slug": p.slug, "title": p.title, "kind": p.kind, "published": p.published}
                for p in rows
            ]
        }

    @router.get("/v1/content/pages/{slug}")
    async def page(slug: str, db: DbDep) -> dict[str, Any]:
        p = await db.get(ContentPage, slug)
        if p is None:
            raise ApiError(404, "not_found", "Sayfa bulunamadı")
        if not p.published:
            # Yayımlanmamış metin (ör. hukuk onayı bekleyen) gösterilmez; durumu açıkça söylenir.
            return {
                **page_view(p, full=False),
                "body": None,
                "pending_note": "Bu metin hukuki inceleme ve onay sürecindedir; yayımlandığında burada görünecek.",
            }
        return page_view(p)

    # --- İçerik yönetimi ve duyuru ---------------------------------------------------------

    @router.get("/admin/v1/content")
    async def admin_content(db: DbDep, _: Principal = _perm("content.manage")) -> dict[str, Any]:
        pages_ = (
            await db.execute(select(ContentPage).order_by(ContentPage.kind, ContentPage.slug))
        ).scalars()
        faq_ = (await db.execute(select(FaqItem).order_by(FaqItem.sort, FaqItem.id))).scalars()
        return {"pages": [page_view(p) for p in pages_], "faq": [faq_view(f) for f in faq_]}

    @router.put("/admin/v1/content/pages/{slug}")
    async def put_page(
        slug: str,
        body: PageBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("content.manage"),
    ) -> dict[str, Any]:
        p = await db.get(ContentPage, slug, with_for_update=True)
        if p is None:
            raise ApiError(404, "not_found", "Sayfa bulunamadı")
        if body.published and len(body.body.strip()) < 50:
            raise ApiError(422, "body_too_short", "Yayımlanacak metin en az 50 karakter olmalı")
        now = services.clock()
        was = p.published
        p.title, p.body, p.published = body.title, body.body, body.published
        p.updated_at, p.updated_by = now, admin.user.id
        if body.published and not was:
            p.published_at = now
        await audit.record(
            db, "content.page_saved", actor_type="admin", actor_id=admin.actor_id, target_type="page",
            target_id=slug, ip=meta.ip, details={"published": body.published, "kind": p.kind, "length": len(body.body)},
        )  # fmt: skip
        return page_view(p)

    @router.post("/admin/v1/content/faq", status_code=201)
    async def add_faq(
        body: FaqBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("content.manage"),
    ) -> dict[str, Any]:
        f = FaqItem(
            question=body.question,
            answer=body.answer,
            sort=body.sort,
            published=body.published,
            updated_at=services.clock(),
        )
        db.add(f)
        await db.flush()
        await audit.record(
            db,
            "content.faq_created",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="faq",
            target_id=str(f.id),
            ip=meta.ip,
        )
        return faq_view(f)

    @router.put("/admin/v1/content/faq/{faq_id}")
    async def put_faq(
        faq_id: int,
        body: FaqBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("content.manage"),
    ) -> dict[str, Any]:
        f = await db.get(FaqItem, faq_id)
        if f is None:
            raise ApiError(404, "not_found", "Soru bulunamadı")
        f.question, f.answer, f.sort, f.published, f.updated_at = (
            body.question,
            body.answer,
            body.sort,
            body.published,
            services.clock(),
        )
        await audit.record(
            db,
            "content.faq_updated",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="faq",
            target_id=str(f.id),
            ip=meta.ip,
        )
        return faq_view(f)

    @router.delete("/admin/v1/content/faq/{faq_id}")
    async def delete_faq(
        faq_id: int, db: DbDep, meta: MetaDep, admin: Principal = _perm("content.manage")
    ) -> dict[str, Any]:
        f = await db.get(FaqItem, faq_id)
        if f is None:
            raise ApiError(404, "not_found", "Soru bulunamadı")
        await db.delete(f)
        await audit.record(
            db,
            "content.faq_deleted",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="faq",
            target_id=str(faq_id),
            ip=meta.ip,
        )
        return {"deleted": faq_id}

    @router.post("/admin/v1/notifications/broadcast")
    async def broadcast(
        body: BroadcastBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("notifications.manage"),
    ) -> dict[str, Any]:
        """Sistem duyurusu: uygulama içi bildirimi kapatmamış tüm aktif kullanıcılara (tek sorgu)."""
        now: datetime = services.clock()
        key = f"broadcast:{int(now.timestamp())}"
        opted_out = select(NotificationPref.user_id).where(
            NotificationPref.category == "system", NotificationPref.in_app.is_(False)
        )
        src = select(
            User.id,
            literal("system", Notification.category.type),
            literal(body.title, Notification.title.type),
            literal(body.body, Notification.body.type),
            literal(body.link, Notification.link.type),
            literal(key, Notification.dedupe_key.type),
            literal(now, Notification.created_at.type),
        ).where(User.status == "active", User.id.not_in(opted_out))
        stmt = (
            insert(Notification)
            .from_select(
                ["user_id", "category", "title", "body", "link", "dedupe_key", "created_at"], src
            )
            .on_conflict_do_nothing()
            .returning(Notification.id)
        )
        count = len((await db.execute(stmt)).scalars().all())
        await audit.record(
            db, "notifications.broadcast", actor_type="admin", actor_id=admin.actor_id, target_type="broadcast",
            target_id=key, ip=meta.ip, details={"title": body.title, "recipients": count},
        )  # fmt: skip
        return {"recipients": count, "key": key}

    return router
