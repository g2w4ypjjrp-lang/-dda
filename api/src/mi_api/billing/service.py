"""Satış, ödeme olayları, abonelikler, iade ve lisans anahtarları.

Ödeme güvenliği (AI Trading Intelligence Aşama 17'deki kanıtlanmış kurallar):

* Sağlayıcı bildirimi **imzası doğrulanmadan** hiçbir şeyi değiştirmez; sahte istek de kaydedilir.
* Aynı olay (sağlayıcı + olay kimliği) yalnızca bir kez işlenir (benzersiz indeks + satır kilidi).
* Sipariş satırı kilitlenir; sipariş başına tek başarılı ödeme. Tutar veya para birimi uyuşmazsa
  abonelik verilmez, sipariş "incelemeye" düşer.
* Ödeme başarılıysa abonelik verilir; aynı planda etkin abonelik varsa süre uzatılır.
* İade sağlayıcı üzerinden yapılır; başarılı iade aboneliği sonlandırır.

Lisans anahtarları ``MI-XXXX-XXXX-XXXX-XXXX`` (Crockford Base32, 80 bit). Düz metin yalnızca
üretimde bir kez gösterilir; veritabanında HMAC-SHA256(pepper) özeti ve son 4 karakter tutulur.
Kullanım hakkı (aktivasyon) sınırı, son kullanma ve iptal desteklenir; başarısız denemeler
sınırlanır ve denetim kaydına yazılır.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.billing.models import (
    License,
    LicenseActivation,
    Order,
    PaymentEventRow,
    PlanPrice,
    Subscription,
)
from mi_api.billing.providers import (
    Buyer,
    CheckoutRequest,
    InvalidSignature,
    IyzicoProvider,
    PaymentEvent,
    PaytrProvider,
    Provider,
    ProviderError,
    SimulatorProvider,
)
from mi_api.config import Settings
from mi_api.engage.notify import notify
from mi_api.errors import ApiError
from mi_api.football.api import TR

PERIOD_DAYS = {"monthly": 30, "yearly": 365}
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


# --- Sağlayıcı ------------------------------------------------------------------------------------


def simulator_secret(settings: Settings) -> bytes:
    if settings.simulator_secret is not None:
        return settings.simulator_secret.get_secret_value().encode()
    kek = settings.secret_kek_bytes() or b"mi-dev-simulator"
    return hmac.new(kek, b"mi.payments.simulator", hashlib.sha256).digest()


def provider_for(settings: Settings, transport: Any = None) -> Provider | None:
    name = settings.payment_provider
    if name == "none":
        return None
    if name == "simulator":
        if settings.is_production_like:
            raise ApiError(503, "simulator_forbidden", "Test ödeme simülatörü bu ortamda kapalı")
        return SimulatorProvider(simulator_secret(settings), settings.public_web_url)
    if name == "paytr":
        if not (
            settings.paytr_merchant_id
            and settings.paytr_merchant_key
            and settings.paytr_merchant_salt
        ):
            raise ApiError(503, "provider_not_configured", "PayTR bilgileri eksik")
        return PaytrProvider(
            merchant_id=settings.paytr_merchant_id,
            merchant_key=settings.paytr_merchant_key.get_secret_value(),
            merchant_salt=settings.paytr_merchant_salt.get_secret_value(),
            test_mode=settings.payments_test_mode,
            transport=transport,
        )
    if not (settings.iyzico_api_key and settings.iyzico_secret_key):
        raise ApiError(503, "provider_not_configured", "iyzico bilgileri eksik")
    return IyzicoProvider(
        api_key=settings.iyzico_api_key.get_secret_value(),
        secret_key=settings.iyzico_secret_key.get_secret_value(),
        test_mode=settings.payments_test_mode,
        transport=transport,
    )


# --- Sipariş --------------------------------------------------------------------------------------


async def active_price(db: AsyncSession, plan: str, period: str) -> PlanPrice:
    price = (
        await db.execute(
            select(PlanPrice).where(
                PlanPrice.plan_code == plan, PlanPrice.period == period, PlanPrice.active
            )
        )
    ).scalar_one_or_none()
    if price is None:
        raise ApiError(
            409, "price_not_set", "Bu paket için henüz fiyat belirlenmedi; satışa kapalı"
        )
    return price


async def create_order(
    db: AsyncSession,
    *,
    settings: Settings,
    provider: Provider,
    user_id: uuid.UUID,
    email: str,
    plan: str,
    period: str,
    buyer: dict[str, str],
    ip: str | None,
    consent: dict[str, Any],
    now: datetime,
) -> tuple[Order, str]:
    price = await active_price(db, plan, period)
    order = Order(
        public_id=uuid.uuid4(),
        user_id=user_id,
        plan_code=plan,
        period=period,
        price_id=price.id,
        amount_minor=price.amount_minor,
        currency=price.currency,
        status="pending",
        provider=provider.name,
        test_mode=provider.test_mode,
        consent=consent,
        created_at=now,
    )
    db.add(order)
    await db.flush()
    result_url = f"{settings.public_web_url}/odeme/sonuc?siparis={order.public_id}"
    request = CheckoutRequest(
        order_id=str(order.public_id),
        order_no=order.id,
        amount_minor=order.amount_minor,
        currency=order.currency,
        item_name=f"Match Intelligence {plan} ({'aylık' if period == 'monthly' else 'yıllık'})",
        plan_code=plan,
        buyer=Buyer(
            customer_id=str(user_id),
            email=email,
            full_name=buyer.get("full_name", ""),
            phone=buyer.get("phone", ""),
            address=buyer.get("address", ""),
            city=buyer.get("city", ""),
            country=buyer.get("country", "Türkiye"),
            ip=ip or "127.0.0.1",
        ),
        success_url=result_url,
        fail_url=result_url,
        callback_url=f"{settings.public_api_url}/v1/billing/webhooks/{provider.name}",
    )
    try:
        session = await provider.create_checkout(request)
    except ProviderError as exc:
        raise ApiError(502, "provider_error", str(exc)) from exc
    order.provider_ref = session.provider_ref
    return order, session.redirect_url


async def find_order(db: AsyncSession, ref: str) -> Order | None:
    stmt = select(Order).with_for_update()
    if ref.startswith("MI") and ref[2:].isdigit():
        return (await db.execute(stmt.where(Order.id == int(ref[2:])))).scalar_one_or_none()
    try:
        public = uuid.UUID(ref)
    except ValueError:
        return None
    return (await db.execute(stmt.where(Order.public_id == public))).scalar_one_or_none()


async def grant_subscription(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    plan: str,
    days: int,
    source: str,
    now: datetime,
    order_id: int | None = None,
    license_id: int | None = None,
    granted_by: uuid.UUID | None = None,
) -> Subscription:
    """Yeni abonelik; aynı planda etkin abonelik varsa yeni dönem onun bitişinden başlar."""
    current = (
        await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.plan_code == plan,
                Subscription.status == "active",
                Subscription.current_period_end > now,
            )
            .order_by(Subscription.current_period_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    start = current.current_period_end if current else now
    sub = Subscription(
        user_id=user_id,
        plan_code=plan,
        status="active",
        source=source,
        started_at=start,
        current_period_end=start + timedelta(days=days),
        order_id=order_id,
        license_id=license_id,
        granted_by=granted_by,
        created_at=now,
    )
    db.add(sub)
    await db.flush()
    end = sub.current_period_end.astimezone(TR).strftime("%d.%m.%Y")
    await notify(
        db,
        user_id,
        "subscription",
        f"{plan} paketiniz etkin",
        f"Paketiniz {end} tarihine kadar geçerli. Otomatik yenileme yoktur.",
        now=now,
        link="/panel",
        dedupe_key=f"subscription:{sub.id}",
    )
    return sub


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def record_event(
    db: AsyncSession,
    *,
    provider: str,
    event: PaymentEvent | None,
    body: bytes,
    valid: bool,
    result: str,
    now: datetime,
    order_id: int | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        PaymentEventRow(
            provider=provider,
            event_id=event.event_id if event else None,
            received_at=now,
            signature_valid=valid,
            event_type=event.event_type if event else None,
            order_id=order_id,
            payload_sha256=_digest(body),
            result=result,
            detail=detail,
        )
    )
    await db.flush()


async def apply_event(
    db: AsyncSession, provider: str, event: PaymentEvent, body: bytes, now: datetime
) -> str:
    """İmzası doğrulanmış olayı uygular. Sonuç kodu döner (denetim ve test için)."""
    duplicate = (
        await db.execute(
            select(PaymentEventRow.id).where(
                PaymentEventRow.provider == provider,
                PaymentEventRow.event_id == event.event_id,
                PaymentEventRow.signature_valid,
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        return "duplicate"
    order = await find_order(db, event.order_ref)
    if order is None:
        await record_event(
            db,
            provider=provider,
            event=event,
            body=body,
            valid=True,
            result="unknown_order",
            now=now,
        )
        return "unknown_order"
    if event.event_type != "payment_succeeded":
        if order.status == "pending":
            order.status = "failed"
        await record_event(
            db,
            provider=provider,
            event=event,
            body=body,
            valid=True,
            result="failed",
            now=now,
            order_id=order.id,
        )
        return "failed"
    if order.status in ("paid", "refunded"):
        order.note = (
            f"İkinci başarılı ödeme bildirimi ({event.provider_payment_id}) — inceleme gerekli"
        )
        await record_event(
            db,
            provider=provider,
            event=event,
            body=body,
            valid=True,
            result="second_payment",
            now=now,
            order_id=order.id,
        )
        return "second_payment"
    if event.amount_minor != order.amount_minor or event.currency.upper() != order.currency:
        order.status = "review"
        order.provider_payment_id = event.provider_payment_id
        order.note = f"Tutar/para birimi uyuşmazlığı: {event.amount_minor} {event.currency}"
        await record_event(
            db,
            provider=provider,
            event=event,
            body=body,
            valid=True,
            result="mismatch",
            now=now,
            order_id=order.id,
        )
        return "mismatch"
    order.status = "paid"
    order.paid_at = now
    order.provider_payment_id = event.provider_payment_id
    await grant_subscription(
        db,
        user_id=order.user_id,
        plan=order.plan_code,
        days=PERIOD_DAYS[order.period],
        source="payment",
        now=now,
        order_id=order.id,
    )
    await record_event(
        db,
        provider=provider,
        event=event,
        body=body,
        valid=True,
        result="paid",
        now=now,
        order_id=order.id,
    )
    return "paid"


async def handle_webhook(
    db: AsyncSession, provider: Any, headers: dict[str, str], body: bytes, now: datetime
) -> str:
    try:
        event = provider.parse_webhook(headers, body)
    except (InvalidSignature, ValueError, KeyError, json.JSONDecodeError) as exc:
        await record_event(
            db,
            provider=provider.name,
            event=None,
            body=body,
            valid=False,
            result="invalid_signature",
            now=now,
            detail=type(exc).__name__,
        )
        return "invalid_signature"
    try:
        async with db.begin_nested():
            return await apply_event(db, provider.name, event, body, now)
    except IntegrityError:
        return "duplicate"  # eşzamanlı aynı olay: benzersiz indeks ikincisini reddetti


async def refund_order(db: AsyncSession, provider: Provider, order: Order, now: datetime) -> str:
    if order.status != "paid" or not order.provider_payment_id:
        raise ApiError(409, "not_refundable", "Yalnızca ödenmiş sipariş iade edilebilir")
    try:
        ref = await provider.refund(
            provider_payment_id=order.provider_payment_id,
            amount_minor=order.amount_minor,
            currency=order.currency,
            order_ref=str(order.public_id),
        )
    except ProviderError as exc:
        raise ApiError(502, "provider_error", str(exc)) from exc
    order.status = "refunded"
    order.refunded_at = now
    order.refund_ref = ref
    await notify(
        db,
        order.user_id,
        "subscription",
        f"Sipariş #{order.id} iade edildi",
        "İade ödeme sağlayıcınıza iletildi; ilgili paket sona erdi.",
        now=now,
        link="/panel",
        dedupe_key=f"refund:{order.id}",
    )
    sub = (
        await db.execute(select(Subscription).where(Subscription.order_id == order.id))
    ).scalar_one_or_none()
    if sub is not None and sub.status == "active":
        sub.status = "refunded"
        sub.canceled_at = now
    return ref


# --- Lisans anahtarları --------------------------------------------------------------------------


def pepper(settings: Settings) -> bytes:
    if settings.license_pepper is None:
        raise ApiError(
            503, "licensing_not_configured", "Lisans sistemi yapılandırılmamış (MI_LICENSE_PEPPER)"
        )
    value = base64.b64decode(settings.license_pepper.get_secret_value())
    if len(value) < 32:
        raise ApiError(503, "licensing_not_configured", "MI_LICENSE_PEPPER en az 32 bayt olmalı")
    return value


def normalize_key(key: str) -> str:
    body = "".join(key.upper().split()).replace("-", "")
    if body.startswith("MI"):
        body = body[2:]
    return body.translate(str.maketrans("ILO", "110"))


def key_digest(settings: Settings, key: str) -> bytes:
    return hmac.new(
        pepper(settings), f"mi-license|{normalize_key(key)}".encode(), hashlib.sha256
    ).digest()


def new_key() -> str:
    body = "".join(secrets.choice(_CROCKFORD) for _ in range(16))  # 80 bit
    return "MI-" + "-".join(body[i : i + 4] for i in range(0, 16, 4))


async def issue_licenses(
    db: AsyncSession,
    settings: Settings,
    *,
    plan: str,
    duration_days: int,
    count: int,
    max_activations: int,
    redeem_days: int,
    created_by: uuid.UUID,
    note: str | None,
    now: datetime,
) -> list[tuple[License, str]]:
    out = []
    for _ in range(count):
        key = new_key()
        lic = License(
            key_digest=key_digest(settings, key),
            key_hint=key[-4:],
            plan_code=plan,
            duration_days=duration_days,
            max_activations=max_activations,
            activations_count=0,
            status="active",
            redeem_before=now + timedelta(days=redeem_days),
            created_at=now,
            created_by=created_by,
            note=note,
        )
        db.add(lic)
        out.append((lic, key))
    await db.flush()
    return out


async def redeem_license(
    db: AsyncSession,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    key: str,
    ip: str | None,
    now: datetime,
) -> Subscription:
    lic = (
        await db.execute(
            select(License).where(License.key_digest == key_digest(settings, key)).with_for_update()
        )
    ).scalar_one_or_none()
    generic = ApiError(
        400, "invalid_license", "Lisans anahtarı geçersiz veya kullanılamaz", commit=True
    )
    if lic is None or lic.status != "active" or lic.redeem_before <= now:
        raise generic
    already = await db.get(LicenseActivation, (lic.id, user_id))
    if already is not None:
        raise ApiError(409, "already_redeemed", "Bu lisansı zaten kullandınız")
    if lic.activations_count >= lic.max_activations:
        raise generic
    sub = await grant_subscription(
        db,
        user_id=user_id,
        plan=lic.plan_code,
        days=lic.duration_days,
        source="license",
        now=now,
        license_id=lic.id,
    )
    lic.activations_count += 1
    db.add(
        LicenseActivation(
            license_id=lic.id, user_id=user_id, activated_at=now, ip=ip, subscription_id=sub.id
        )
    )
    await db.flush()
    return sub
