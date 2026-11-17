"""Tasarım sistemleri ve Design Studio API'si.

Herkese açık: ``GET /v1/design`` — yayımlanmış on tasarımın yapılandırması ve site varsayılanı
(web sunucusu sayfayı bu yapılandırmayla işler; önbelleğe alınabilir).

Yönetim (``/admin/v1/design``):
* ``design.read``: tasarımlar, sürüm geçmişi, tek sürüm (taslak önizlemesi için).
* ``design.edit``: taslak oluşturma (yayımlanmış veya belirli bir sürümden), taslak düzenleme,
  taslağı atma.
* ``design.publish`` (hassas, yeniden doğrulama + açık onay): taslağı yayımlama, eski sürüme
  dönme (eski yapılandırma **yeni sürüm** olarak yayımlanır; geçmiş silinmez), site
  varsayılanını değiştirme.

Tüm değişiklikler denetim kaydına yazılır. Yapılandırma katı şemayla doğrulanır (``schema.py``).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api import audit
from mi_api.context import DbDep, MetaDep, Principal, ServicesDep, require_permission
from mi_api.design.defaults import ORDER
from mi_api.design.models import DesignSettings, DesignVersion
from mi_api.design.schema import DesignConfig
from mi_api.errors import ApiError


def _perm(code: str) -> Any:
    return Depends(require_permission(code))


class DraftCreate(BaseModel):
    from_version_id: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=300)


class DraftUpdate(BaseModel):
    config: dict[str, Any]
    note: str | None = Field(default=None, max_length=300)


class Confirm(BaseModel):
    confirm: Literal[True]  # yayın öncesi açık onay
    note: str | None = Field(default=None, max_length=300)


class DefaultBody(BaseModel):
    design_key: str = Field(max_length=32)
    confirm: Literal[True]


def version_view(v: DesignVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "design_key": v.design_key,
        "version": v.version,
        "status": v.status,
        "note": v.note,
        "based_on": v.based_on,
        "created_at": v.created_at.isoformat(),
        "updated_at": v.updated_at.isoformat(),
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "config": v.config,
    }


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return DesignConfig.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        fields = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()[:20]]
        raise ApiError(422, "invalid_design", f"Tasarım yapılandırması geçersiz: {fields}") from exc


async def published(db: AsyncSession) -> dict[str, DesignVersion]:
    rows = (
        await db.execute(select(DesignVersion).where(DesignVersion.status == "published"))
    ).scalars()
    return {r.design_key: r for r in rows}


async def default_key(db: AsyncSession) -> str:
    row = await db.get(DesignSettings, 1)
    return row.default_design if row else ORDER[0]


async def _version(db: AsyncSession, version_id: int, *, lock: bool = False) -> DesignVersion:
    v = await db.get(DesignVersion, version_id, with_for_update=lock)
    if v is None:
        raise ApiError(404, "not_found", "Tasarım sürümü bulunamadı")
    return v


def _known(key: str) -> None:
    if key not in ORDER:
        raise ApiError(404, "not_found", "Bilinmeyen tasarım")


def create_design_router() -> APIRouter:
    router = APIRouter(tags=["design"])

    @router.get("/v1/design")
    async def public_design(db: DbDep) -> JSONResponse:
        pub = await published(db)
        body = {
            "default": await default_key(db),
            "order": [k for k in ORDER if k in pub],
            "designs": {
                k: {"version": pub[k].version, "config": pub[k].config} for k in ORDER if k in pub
            },
        }
        return JSONResponse(body, headers={"Cache-Control": "public, max-age=30"})

    @router.get("/admin/v1/design")
    async def admin_list(db: DbDep, _: Principal = _perm("design.read")) -> dict[str, Any]:
        pub = await published(db)
        drafts = {
            r.design_key: r
            for r in (
                await db.execute(select(DesignVersion).where(DesignVersion.status == "draft"))
            ).scalars()
        }
        counts = dict(
            (
                await db.execute(
                    select(DesignVersion.design_key, func.count()).group_by(
                        DesignVersion.design_key
                    )
                )
            ).all()
        )
        return {
            "default": await default_key(db),
            "items": [
                {
                    "key": k,
                    "published": version_view(pub[k]) if k in pub else None,
                    "draft": version_view(drafts[k]) if k in drafts else None,
                    "versions": int(counts.get(k, 0)),
                }
                for k in ORDER
            ],
        }

    @router.get("/admin/v1/design/{key}/versions")
    async def history(key: str, db: DbDep, _: Principal = _perm("design.read")) -> dict[str, Any]:
        _known(key)
        rows = (
            await db.execute(
                select(DesignVersion)
                .where(DesignVersion.design_key == key)
                .order_by(DesignVersion.version.desc())
            )
        ).scalars()
        return {"items": [version_view(r) for r in rows]}

    @router.get("/admin/v1/design/versions/{version_id}")
    async def get_version(
        version_id: int, db: DbDep, _: Principal = _perm("design.read")
    ) -> dict[str, Any]:
        return version_view(await _version(db, version_id))

    @router.post("/admin/v1/design/{key}/drafts", status_code=201)
    async def create_draft(
        key: str,
        body: DraftCreate,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("design.edit"),
    ) -> dict[str, Any]:
        _known(key)
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"design:{key}"))))
        existing = (
            await db.execute(
                select(DesignVersion).where(
                    DesignVersion.design_key == key, DesignVersion.status == "draft"
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ApiError(409, "draft_exists", "Bu tasarımın açık bir taslağı zaten var")
        if body.from_version_id is not None:
            source = await _version(db, body.from_version_id)
            if source.design_key != key:
                raise ApiError(422, "wrong_design", "Kaynak sürüm bu tasarıma ait değil")
        else:
            source = (await published(db)).get(key)  # type: ignore[assignment]
            if source is None:
                raise ApiError(409, "no_published", "Yayımlanmış sürüm yok")
        last = (
            await db.execute(
                select(func.max(DesignVersion.version)).where(DesignVersion.design_key == key)
            )
        ).scalar_one()
        now = services.clock()
        draft = DesignVersion(
            design_key=key,
            version=int(last or 0) + 1,
            status="draft",
            config=validate_config(source.config),
            note=body.note,
            based_on=source.id,
            created_at=now,
            created_by=admin.user.id,
            updated_at=now,
        )
        db.add(draft)
        await db.flush()
        await audit.record(
            db,
            "design.draft_created",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="design",
            target_id=f"{key}#{draft.version}",
            ip=meta.ip,
            details={"based_on": source.id},
        )
        return version_view(draft)

    @router.put("/admin/v1/design/versions/{version_id}")
    async def update_draft(
        version_id: int,
        body: DraftUpdate,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("design.edit"),
    ) -> dict[str, Any]:
        v = await _version(db, version_id, lock=True)
        if v.status != "draft":
            raise ApiError(409, "not_draft", "Yalnızca taslak düzenlenebilir")
        v.config = validate_config(body.config)
        if body.note is not None:
            v.note = body.note
        v.updated_at = services.clock()
        await audit.record(
            db,
            "design.draft_updated",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="design",
            target_id=f"{v.design_key}#{v.version}",
            ip=meta.ip,
        )
        return version_view(v)

    @router.post("/admin/v1/design/versions/{version_id}/discard")
    async def discard(
        version_id: int,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("design.edit"),
    ) -> dict[str, Any]:
        v = await _version(db, version_id, lock=True)
        if v.status != "draft":
            raise ApiError(409, "not_draft", "Yalnızca taslak atılabilir")
        v.status = "discarded"
        v.updated_at = services.clock()
        await audit.record(
            db,
            "design.draft_discarded",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="design",
            target_id=f"{v.design_key}#{v.version}",
            ip=meta.ip,
        )
        return version_view(v)

    async def _publish(
        db: AsyncSession, v: DesignVersion, admin: Principal, now: Any
    ) -> DesignVersion | None:
        current = (await published(db)).get(v.design_key)
        if current is not None:
            current.status = "archived"
            await db.flush()  # tek yayımlanmış sürüm indeksinden önce
        v.status = "published"
        v.published_at = now
        v.published_by = admin.user.id
        v.updated_at = now
        await db.flush()
        return current

    @router.post("/admin/v1/design/versions/{version_id}/publish")
    async def publish(
        version_id: int,
        body: Confirm,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("design.publish"),
    ) -> dict[str, Any]:
        v = await _version(db, version_id, lock=True)
        if v.status != "draft":
            raise ApiError(409, "not_draft", "Yalnızca taslak yayımlanabilir")
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(f"design:{v.design_key}")))
        )
        validate_config(v.config)
        if body.note:
            v.note = body.note
        previous = await _publish(db, v, admin, services.clock())
        await audit.record(
            db,
            "design.published",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="design",
            target_id=f"{v.design_key}#{v.version}",
            ip=meta.ip,
            details={"previous_version": previous.version if previous else None},
        )
        return version_view(v)

    @router.post("/admin/v1/design/versions/{version_id}/rollback")
    async def rollback(
        version_id: int,
        body: Confirm,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("design.publish"),
    ) -> dict[str, Any]:
        """Eski bir sürümün yapılandırmasını **yeni sürüm** olarak yayımlar (geçmiş korunur)."""
        source = await _version(db, version_id)
        if source.status not in ("published", "archived"):
            raise ApiError(
                409, "not_published_before", "Yalnızca daha önce yayımlanmış sürüme dönülebilir"
            )
        if source.status == "published":
            raise ApiError(409, "already_current", "Bu sürüm zaten yayında")
        key = source.design_key
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"design:{key}"))))
        open_draft = (
            await db.execute(
                select(DesignVersion).where(
                    DesignVersion.design_key == key, DesignVersion.status == "draft"
                )
            )
        ).scalar_one_or_none()
        if open_draft is not None:
            raise ApiError(409, "draft_exists", "Önce açık taslağı yayımlayın veya atın")
        last = (
            await db.execute(
                select(func.max(DesignVersion.version)).where(DesignVersion.design_key == key)
            )
        ).scalar_one()
        now = services.clock()
        restored = DesignVersion(
            design_key=key,
            version=int(last) + 1,
            status="draft",
            config=source.config,
            note=body.note or f"v{source.version} sürümüne dönüldü",
            based_on=source.id,
            created_at=now,
            created_by=admin.user.id,
            updated_at=now,
        )
        db.add(restored)
        await db.flush()
        previous = await _publish(db, restored, admin, now)
        await audit.record(
            db,
            "design.rolled_back",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="design",
            target_id=f"{key}#{restored.version}",
            ip=meta.ip,
            details={
                "restored_from": source.version,
                "previous_version": previous.version if previous else None,
            },
        )
        return version_view(restored)

    @router.put("/admin/v1/design/default")
    async def set_default(
        body: DefaultBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("design.publish"),
    ) -> dict[str, Any]:
        _known(body.design_key)
        if body.design_key not in await published(db):
            raise ApiError(
                409, "no_published", "Yayımlanmış sürümü olmayan tasarım varsayılan olamaz"
            )
        row = await db.get(DesignSettings, 1, with_for_update=True)
        before = row.default_design if row else None
        if row is None:
            row = DesignSettings(id=1, default_design=body.design_key, updated_at=services.clock())
            db.add(row)
        row.default_design = body.design_key
        row.updated_at = services.clock()
        row.updated_by = admin.user.id
        await audit.record(
            db,
            "design.default_changed",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="design",
            target_id=body.design_key,
            ip=meta.ip,
            details={"from": before, "to": body.design_key},
        )
        return {"default": body.design_key}

    return router
