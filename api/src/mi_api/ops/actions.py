# ruff: noqa: E501
"""Admin Action Center: dikkat gerektiren durumlar, her istekte gerçek kayıtlardan hesaplanır.

Kaynaklar: 5xx hataları (metrik halkası), ödeme sorunları (incelemedeki sipariş, imzası geçersiz
bildirim), veri işleri (başarısız senkronizasyon, sağlayıcı yok), model uyarıları (şampiyon yok,
kayma, yüksek çekimserlik), işçi/zamanlayıcı kalp atışı, bekleyen işler (açık tasarım taslağı,
sonuçlandırılmamış kupon seçimi).

Her uyarının kimliği sorunun kendisini içerir (ör. ``sync_run:123``). "Görüldü" işareti yalnızca o
kimliği gizler; aynı türden yeni bir sorun yeni kimlikle yeniden görünür.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.billing.models import Order, PaymentEventRow
from mi_api.config import Settings
from mi_api.coupons.models import CouponLeg
from mi_api.design.models import DesignVersion
from mi_api.football.api import TR
from mi_api.football.models import Fixture, SyncRun
from mi_api.ops.health import HEARTBEAT_KEY, HEARTBEAT_STALE
from mi_api.ops.metrics import Metrics
from mi_api.ops.models import ActionAck, ApprovalRequest, Backup
from mi_api.ops.overview import ai as ai_section
from mi_api.predictions.models import ModelVersion, Prediction


@dataclass
class Issue:
    key: str
    category: str  # errors | payments | data | models | tasks | pending
    severity: str  # critical | warning | info
    title: str
    detail: str
    link: str | None
    at: str | None
    permission: str


async def collect(
    db: AsyncSession, settings: Settings, redis: Redis | None, metrics: Metrics, now: datetime
) -> list[Issue]:
    out: list[Issue] = []

    hour = await metrics.window(60)
    if hour["errors_5xx"]:
        out.append(
            Issue(
                f"errors:{now:%Y%m%d%H}",
                "errors",
                "critical",
                f"Son 1 saatte {hour['errors_5xx']} sunucu hatası (5xx)",
                f"{hour['requests']} istekte hata oranı %{(hour['error_rate'] or 0) * 100:.1f}. Ayrıntı Sistem Sağlığı → son hatalar.",
                "/yonetim/sistem",
                now.isoformat(),
                "system.read",
            )
        )

    for o in (
        await db.execute(select(Order).where(Order.status == "review").order_by(Order.id))
    ).scalars():
        out.append(
            Issue(
                f"order_review:{o.id}",
                "payments",
                "critical",
                f"Sipariş #{o.id} incelemede",
                o.note or "Ödeme bildirimi siparişle uyuşmadı; abonelik verilmedi.",
                "/yonetim/aksiyon",
                o.created_at.isoformat(),
                "finance.read",
            )
        )
    day = now.astimezone(TR).date()
    bad_sig = (
        await db.execute(
            select(func.count())
            .select_from(PaymentEventRow)
            .where(
                PaymentEventRow.signature_valid.is_(False),
                PaymentEventRow.received_at >= now - timedelta(hours=24),
            )
        )
    ).scalar_one()
    if bad_sig:
        out.append(
            Issue(
                f"invalid_signature:{day}",
                "payments",
                "warning",
                f"Son 24 saatte {bad_sig} imzası geçersiz ödeme bildirimi",
                "Bildirimler hiçbir şeyi değiştirmedi; tekrarlıyorsa sağlayıcı anahtarlarını ve kaynak IP'leri inceleyin.",
                "/yonetim/finans",
                None,
                "finance.read",
            )
        )

    if settings.football_provider == "none":
        out.append(
            Issue(
                "football_provider:none",
                "data",
                "warning",
                "Futbol veri sağlayıcısı yapılandırılmamış",
                "Gerçek maç verisi için M-G1 onayı ve API anahtarı gerekli (MI_FOOTBALL_PROVIDER / MI_FOOTBALL_API_KEY).",
                "/yonetim/veri",
                None,
                "football.read",
            )
        )
    failed = (
        await db.execute(
            select(SyncRun)
            .where(SyncRun.status == "failed", SyncRun.started_at >= now - timedelta(hours=24))
            .order_by(SyncRun.started_at.desc())
            .limit(20)
        )
    ).scalars()
    for r in failed:
        out.append(
            Issue(
                f"sync_run:{r.id}",
                "data",
                "critical",
                f"Veri işi başarısız: {r.job}",
                r.message or "Ayrıntı yok",
                "/yonetim/veri",
                r.started_at.isoformat(),
                "football.read",
            )
        )

    champions = (
        await db.execute(
            select(func.count()).select_from(ModelVersion).where(ModelVersion.status == "champion")
        )
    ).scalar_one()
    if not champions:
        out.append(
            Issue(
                "models:no_champion",
                "models",
                "warning",
                "Şampiyon model yok",
                "Tahmin üretilemez; Model Lab'den eğitim başlatın.",
                "/yonetim/modeller",
                None,
                "models.read",
            )
        )
    for d in (await ai_section(db, now))["drift"]:
        out.append(
            Issue(
                f"drift:{d['model_version_id']}",
                "models",
                "warning",
                f"Model kayması: {d['scope_key']}",
                f"Canlı log loss {d['live_log_loss']:.3f} > test {d['test_log_loss']:.3f} ({d['n']} maç). Yeniden eğitim önerilir.",
                "/yonetim/modeller",
                None,
                "models.read",
            )
        )
    start = now.astimezone(TR).replace(hour=0, minute=0, second=0, microsecond=0)
    today = dict(
        (
            await db.execute(
                select(Prediction.status, func.count())
                .where(Prediction.created_at >= start)
                .group_by(Prediction.status)
            )
        ).all()
    )
    total = sum(today.values())
    if total >= 5 and today.get("abstained", 0) / total > 0.5:
        out.append(
            Issue(
                f"abstain:{day}",
                "models",
                "info",
                f"Bugün tahminlerin %{today['abstained'] / total * 100:.0f}'i çekimser",
                "Veri eksikliği veya model güvenilirliği nedeniyle; nedenler tahmin kayıtlarında.",
                "/yonetim/modeller",
                None,
                "models.read",
            )
        )

    if redis is not None:
        try:
            raw = await redis.get(HEARTBEAT_KEY)
        except Exception:
            raw = None
        last = (
            datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw) if raw else None
        )
        if last is None or now - last > HEARTBEAT_STALE:
            out.append(
                Issue(
                    "worker:heartbeat",
                    "tasks",
                    "critical" if last else "warning",
                    "Arka plan işçisi/zamanlayıcı yanıt vermiyor"
                    if last
                    else "Arka plan işçisinden hiç kalp atışı alınmadı",
                    f"Son kalp atışı: {last.isoformat() if last else 'yok'}. Veri senkronizasyonu ve kupon sonuçlandırma çalışmıyor olabilir.",
                    "/yonetim/sistem",
                    last.isoformat() if last else None,
                    "system.read",
                )
            )

    for v in (
        await db.execute(select(DesignVersion).where(DesignVersion.status == "draft"))
    ).scalars():
        out.append(
            Issue(
                f"design_draft:{v.id}",
                "pending",
                "info",
                f"Yayımlanmamış tasarım taslağı: {v.config.get('name', v.design_key)} v{v.version}",
                "Taslak yayımlanana veya atılana kadar bekler.",
                "/yonetim/tasarim",
                v.updated_at.isoformat(),
                "design.read",
            )
        )
    out += await _backup_issues(db, settings, now)
    for req in (
        await db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at > now)
            .order_by(ApprovalRequest.id)
        )
    ).scalars():
        out.append(
            Issue(
                f"approval:{req.id}",
                "pending",
                "warning",
                f"Onay bekleyen işlem #{req.id}: {req.summary}",
                f"İkinci bir yönetici onaylamalı ya da reddetmeli; son: {req.expires_at:%d.%m %H:%M} UTC.",
                "/yonetim/onaylar",
                req.requested_at.isoformat(),
                req.permission,
            )
        )
    stuck = (
        await db.execute(
            select(func.count())
            .select_from(CouponLeg)
            .join(Fixture, Fixture.id == CouponLeg.fixture_id)
            .where(
                CouponLeg.result == "pending",
                Fixture.status == "finished",
                Fixture.kickoff_at < now - timedelta(hours=6),
            )
        )
    ).scalar_one()
    if stuck:
        out.append(
            Issue(
                f"coupon_unsettled:{day}",
                "pending",
                "warning",
                f"{stuck} kupon seçimi biten maçta sonuçlanmadı",
                "Sonuçlandırma işi çalışmamış veya İY skoru eksik olabilir. Kupon Yönetimi → Şimdi sonuçlandır.",
                "/yonetim/kuponlar",
                None,
                "coupons.read",
            )
        )
    return out


async def _backup_issues(db: AsyncSession, settings: Settings, now: datetime) -> list[Issue]:
    out: list[Issue] = []
    if not settings.backup_dir:
        if settings.environment in ("staging", "production"):
            out.append(
                Issue("backup_unconfigured", "data", "critical", "Yedekleme yapılandırılmamış",
                      "MI_BACKUP_DIR ayarlanmadan veritabanı yedeği alınmaz.", "/yonetim/yedekler", None, "system.read")
            )  # fmt: skip
        return out
    last = (
        await db.execute(select(Backup).order_by(Backup.created_at.desc()).limit(1))
    ).scalar_one_or_none()
    last_ok = (
        await db.execute(
            select(Backup)
            .where(Backup.status.in_(("ok", "pruned")))
            .order_by(Backup.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is not None and last.status == "failed":
        out.append(
            Issue(f"backup_failed:{last.id}", "data", "critical", "Son yedekleme başarısız",
                  (last.error or "")[:200], "/yonetim/yedekler", last.created_at.isoformat(), "system.read")
        )  # fmt: skip
    if last_ok is None or now - last_ok.created_at > timedelta(hours=26):
        since = (
            f"son başarılı yedek: {last_ok.created_at:%d.%m %H:%M} UTC"
            if last_ok
            else "hiç başarılı yedek yok"
        )
        out.append(
            Issue(f"backup_stale:{now:%Y%m%d}", "data", "critical", "Son 26 saatte başarılı yedek yok",
                  since, "/yonetim/yedekler", last_ok.created_at.isoformat() if last_ok else None, "system.read")
        )  # fmt: skip
    if last_ok is not None and last_ok.verify_ok is False:
        out.append(
            Issue(f"backup_verify:{last_ok.id}", "data", "critical", "Son yedeğin geri yükleme doğrulaması başarısız",
                  "Yedek dosyası geri yüklenemedi ya da denetimler tutmadı; ayrıntı Yedekler sayfasında.",
                  "/yonetim/yedekler", (last_ok.verified_at or last_ok.created_at).isoformat(), "system.read")
        )  # fmt: skip
    return out


async def visible(
    db: AsyncSession, issues: list[Issue], permissions: frozenset[str], include_acked: bool
) -> list[dict[str, Any]]:
    keys = [i.key for i in issues]
    acks = (
        {
            a.issue_key: a
            for a in (
                await db.execute(select(ActionAck).where(ActionAck.issue_key.in_(keys)))
            ).scalars()
        }
        if keys
        else {}
    )
    order = {"critical": 0, "warning": 1, "info": 2}
    rows = []
    for i in sorted(issues, key=lambda x: (order[x.severity], x.key)):
        if i.permission not in permissions:
            continue
        ack = acks.get(i.key)
        if ack and not include_acked:
            continue
        rows.append(
            {
                **asdict(i),
                "acked": {"at": ack.acked_at.isoformat(), "note": ack.note} if ack else None,
            }
        )
    return rows
