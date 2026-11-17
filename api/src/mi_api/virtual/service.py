"""Sanal portföy: hesap, tutar (stake) hesaplama, risk sınırları, bilet sonuçlandırma, raporlar.

**Sanal birim (SB) gerçek para değildir.** Çekilemez, transfer edilemez, satın alınamaz. Sonuçlar
"simüle edilmiş" olarak etiketlenir; gerçek kazanç gibi gösterilmez.

Oran kaynağı (lisanslı oran verisi M-G2 bağlanana kadar):

* ``model_fair`` — model adil oranı = 1 / birleşik olasılık (marjsız). **Piyasa oranı değildir.**
  Model iyi kalibre ise beklenen sanal kâr sıfırdır; sonuç esasen modelin kalibrasyonunu ve şansı
  gösterir. Kelly bu oranda avantaj görmez ve işlem önermez.
* ``user_entered`` — kullanıcının girdiği oran. Doğrulanmamıştır; EV bu orana göre hesaplanır ve
  "doğrulanmamış oran" olarak etiketlenir.

Tutar yöntemleri: sabit tutar, bakiyenin sabit yüzdesi, kesirli Kelly. Her yöntemde tek bilet
bakiyenin ``max_stake_pct``'ünü, günlük toplam ``daily_risk_pct``'yi, günlük bilet sayısı
``max_daily_tickets``'ı aşamaz.

**Kayıp kovalamaya karşı:** riski artıran ayar değişiklikleri (daha büyük tutar/yüzde/Kelly kesri,
daha yüksek sınırlar, yöntem değişikliği) Türkiye saatiyle **ertesi gün** geçerli olur; riski
azaltanlar hemen. "Kayıptan sonra tutarı katla" gibi bir seçenek yoktur. Sıfırlama 7 günde bir ve
bekleyen bilet yokken yapılabilir; sıfırlama sayısı raporlarda görünür.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.coupons.models import Coupon
from mi_api.errors import ApiError
from mi_api.football.api import TR
from mi_api.virtual.models import Ledger, Ticket, VirtualAccount

UNIT = 100  # 1 SB = 100 minor
STARTING_BALANCE = 10_000 * UNIT
MIN_STAKE = 1 * UNIT
RESET_COOLDOWN = timedelta(days=7)
DISCLAIMER = (
    "Sanal birim (SB) gerçek para değildir; çekilemez, transfer edilemez, satın alınamaz. "
    "Sonuçlar simülasyondur ve gerçek kazanç anlamına gelmez."
)
FAIR_NOTE = (
    "Model adil oranı (1 / olasılık) bir piyasa oranı değildir; model iyi kalibre ise beklenen "
    "sanal kâr sıfırdır."
)
USER_ODDS_NOTE = "Girdiğiniz oran doğrulanmamıştır; EV bu orana göre hesaplanır."


class Settings(BaseModel):
    method: Literal["fixed", "percent", "kelly"] = "percent"
    fixed_minor: int = Field(default=100 * UNIT, ge=MIN_STAKE, le=5_000 * UNIT)
    percent: float = Field(default=1.0, ge=0.1, le=5.0)
    kelly_fraction: float = Field(default=0.25, ge=0.05, le=0.5)
    max_stake_pct: float = Field(default=5.0, ge=0.5, le=10.0)
    daily_risk_pct: float = Field(default=10.0, ge=1.0, le=25.0)
    max_daily_tickets: int = Field(default=5, ge=1, le=20)


RISK_FIELDS = (
    "fixed_minor",
    "percent",
    "kelly_fraction",
    "max_stake_pct",
    "daily_risk_pct",
    "max_daily_tickets",
)


def increases_risk(old: Settings, new: Settings) -> bool:
    if new.method != old.method:
        return True
    return any(getattr(new, f) > getattr(old, f) for f in RISK_FIELDS)


def next_tr_midnight(now: datetime) -> datetime:
    local = now.astimezone(TR)
    return datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=TR).astimezone(UTC)


def tr_day_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(TR).date(), time.min, tzinfo=TR).astimezone(UTC)


def fair_odds(p: float) -> Decimal:
    return max(
        Decimal("1.001"),
        (Decimal(1) / Decimal(str(p))).quantize(Decimal("0.001"), rounding=ROUND_DOWN),
    )


def kelly_fraction(p: float, odds: float) -> float:
    """Tam Kelly: f* = (p·o − 1) / (o − 1); avantaj yoksa 0."""
    return max(0.0, (p * odds - 1) / (odds - 1))


async def get_account(
    db: AsyncSession, user_id: Any, now: datetime, *, lock: bool = False
) -> VirtualAccount:
    stmt = select(VirtualAccount).where(VirtualAccount.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is None:
        raise ApiError(404, "no_account", "Sanal portföy henüz açılmadı")
    if (
        account.pending_settings
        and account.pending_effective_at
        and account.pending_effective_at <= now
    ):
        account.settings = account.pending_settings
        account.pending_settings = None
        account.pending_effective_at = None
    return account


async def open_account(db: AsyncSession, user_id: Any, now: datetime) -> VirtualAccount:
    existing = (
        await db.execute(select(VirtualAccount).where(VirtualAccount.user_id == user_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "account_exists", "Sanal portföyünüz zaten var")
    account = VirtualAccount(
        user_id=user_id,
        created_at=now,
        starting_balance_minor=STARTING_BALANCE,
        balance_minor=0,
        settings=Settings().model_dump(),
        reset_count=0,
    )
    db.add(account)
    await db.flush()
    db.add(
        Ledger(
            account_id=account.id,
            created_at=now,
            kind="opening",
            amount_minor=STARTING_BALANCE,
            balance_minor=0,
            note="Açılış",
        )
    )
    await db.flush()
    await db.refresh(account)
    return account


async def update_settings(
    db: AsyncSession, account: VirtualAccount, new: Settings, now: datetime
) -> dict[str, Any]:
    old = Settings(**account.settings)
    if increases_risk(old, new):
        account.pending_settings = new.model_dump()
        account.pending_effective_at = next_tr_midnight(now)
        return {
            "applied": False,
            "effective_at": account.pending_effective_at.isoformat(),
            "detail": "Riski artıran değişiklikler ertesi gün (TR 00:00) geçerli olur.",
        }
    account.settings = new.model_dump()
    account.pending_settings = None
    account.pending_effective_at = None
    return {"applied": True, "effective_at": now.isoformat(), "detail": "Ayarlar hemen uygulandı."}


async def _day_stats(
    db: AsyncSession, account: VirtualAccount, now: datetime
) -> tuple[int, int, int]:
    """(bugünkü bilet sayısı, bugünkü toplam tutar, gün başı bakiyesi)."""
    start = tr_day_start(now)
    count, staked = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Ticket.stake_minor), 0)).where(
                Ticket.account_id == account.id, Ticket.created_at >= start
            )
        )
    ).one()
    before = (
        await db.execute(
            select(Ledger.balance_minor)
            .where(Ledger.account_id == account.id, Ledger.created_at < start)
            .order_by(Ledger.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return (
        int(count),
        int(staked),
        int(before if before is not None else account.balance_minor + staked),
    )


def compute_stake(
    settings: Settings, balance: int, p: float, odds: float
) -> tuple[int, dict[str, Any]]:
    detail: dict[str, Any] = {"method": settings.method}
    if settings.method == "fixed":
        raw = settings.fixed_minor
    elif settings.method == "percent":
        raw = math.floor(balance * settings.percent / 100 + 1e-6)
        detail["percent"] = settings.percent
    else:
        full = kelly_fraction(p, odds)
        detail.update(kelly_full=full, kelly_fraction=settings.kelly_fraction)
        if full <= 0:
            raise ApiError(
                422,
                "no_edge",
                "Kelly işlem önermiyor: model olasılığı bu oranda pozitif beklenti "
                "göstermiyor (işlem yapmamak da bir karardır).",
            )
        raw = math.floor(balance * full * settings.kelly_fraction + 1e-6)  # kayan nokta payı
    cap = math.floor(balance * settings.max_stake_pct / 100 + 1e-6)
    stake = min(raw, cap)
    detail.update(raw_minor=raw, cap_minor=cap, capped=raw > cap)
    if stake < MIN_STAKE:
        raise ApiError(422, "stake_too_small", "Hesaplanan tutar 1 SB'nin altında; bilet açılmadı")
    return stake, detail


async def place_ticket(
    db: AsyncSession,
    account: VirtualAccount,
    coupon: Coupon,
    *,
    odds_source: Literal["model_fair", "user_entered"],
    user_odds: Decimal | None,
    now: datetime,
) -> Ticket:
    if coupon.status != "pending" or coupon.first_kickoff_at <= now:
        raise ApiError(422, "coupon_closed", "Kuponun ilk maçı başladı veya kupon sonuçlandı")
    p = coupon.joint_probability
    if p <= 0:
        raise ApiError(422, "zero_probability", "Kuponun model olasılığı sıfır")
    if odds_source == "model_fair":
        odds = fair_odds(p)
    else:
        if user_odds is None:
            raise ApiError(422, "odds_required", "Oran girin")
        odds = user_odds.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    settings = Settings(**account.settings)
    count, staked_today, day_start = await _day_stats(db, account, now)
    if count >= settings.max_daily_tickets:
        raise ApiError(
            422, "daily_ticket_limit", f"Günlük bilet sınırı doldu ({settings.max_daily_tickets})"
        )
    stake, detail = compute_stake(settings, account.balance_minor, p, float(odds))
    daily_cap = math.floor(day_start * settings.daily_risk_pct / 100)
    if staked_today + stake > daily_cap:
        raise ApiError(
            422,
            "daily_risk_limit",
            f"Günlük risk sınırı (%{settings.daily_risk_pct:g}) aşılacaktı; bilet açılmadı",
        )
    ticket = Ticket(
        account_id=account.id,
        coupon_id=coupon.id,
        created_at=now,
        stake_minor=stake,
        odds=odds,
        odds_source=odds_source,
        model_probability=p,
        staking={**detail, "daily_cap_minor": daily_cap},
        status="pending",
    )
    db.add(ticket)
    await db.flush()
    db.add(
        Ledger(
            account_id=account.id,
            created_at=now,
            kind="stake",
            amount_minor=-stake,
            balance_minor=0,
            ticket_id=ticket.id,
        )
    )
    await db.flush()
    await db.refresh(account)
    return ticket


async def settle_tickets(
    db: AsyncSession, coupon: Coupon, has_void_leg: bool, now: datetime
) -> int:
    tickets = (
        (
            await db.execute(
                select(Ticket)
                .where(Ticket.coupon_id == coupon.id, Ticket.status == "pending")
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for t in tickets:
        if coupon.status == "lost":
            t.status, t.payout_minor = "lost", 0
        elif coupon.status == "void" or (coupon.status == "won" and has_void_leg):
            # Geçersiz seçim olan kazanan kuponda oran yeniden hesaplanamaz: tutar iade edilir.
            t.status, t.payout_minor = "void", t.stake_minor
        else:
            t.status, t.payout_minor = "won", math.floor(t.stake_minor * Decimal(t.odds))
        t.settled_at = now
        await db.flush()
        if t.payout_minor:
            kind = "payout" if t.status == "won" else "refund"
            db.add(
                Ledger(
                    account_id=t.account_id,
                    created_at=now,
                    kind=kind,
                    amount_minor=t.payout_minor,
                    balance_minor=0,
                    ticket_id=t.id,
                )
            )
    await db.flush()
    return len(tickets)


async def reset_account(db: AsyncSession, account: VirtualAccount, now: datetime) -> None:
    if account.last_reset_at and now - account.last_reset_at < RESET_COOLDOWN:
        raise ApiError(
            422, "reset_cooldown", "Sanal portföy 7 günde en fazla bir kez sıfırlanabilir"
        )
    pending = (
        await db.execute(
            select(func.count()).where(Ticket.account_id == account.id, Ticket.status == "pending")
        )
    ).scalar_one()
    if pending:
        raise ApiError(422, "pending_tickets", "Bekleyen biletler sonuçlanmadan sıfırlanamaz")
    db.add(
        Ledger(
            account_id=account.id,
            created_at=now,
            kind="reset",
            amount_minor=account.starting_balance_minor - account.balance_minor,
            balance_minor=0,
            note="Sıfırlama",
        )
    )
    account.reset_count += 1
    account.last_reset_at = now
    await db.flush()
    await db.refresh(account)


def max_drawdown(balances: list[int]) -> float:
    peak, worst = 0, 0.0
    for b in balances:
        peak = max(peak, b)
        if peak > 0:
            worst = max(worst, (peak - b) / peak)
    return worst


async def report(
    db: AsyncSession, account: VirtualAccount, start: datetime | None, end: datetime | None
) -> dict[str, Any]:
    tq = select(Ticket).where(Ticket.account_id == account.id)
    lq = select(Ledger).where(Ledger.account_id == account.id)
    if start:
        tq, lq = tq.where(Ticket.created_at >= start), lq.where(Ledger.created_at >= start)
    if end:
        tq, lq = tq.where(Ticket.created_at < end), lq.where(Ledger.created_at < end)
    tickets = (await db.execute(tq.order_by(Ticket.id))).scalars().all()
    ledger = (await db.execute(lq.order_by(Ledger.id))).scalars().all()
    settled = [t for t in tickets if t.status in ("won", "lost")]
    staked = sum(t.stake_minor for t in settled)
    returned = sum(t.payout_minor or 0 for t in settled)
    by_source: dict[str, dict[str, Any]] = {}
    for src in ("model_fair", "user_entered"):
        s = [t for t in settled if t.odds_source == src]
        st = sum(t.stake_minor for t in s)
        by_source[src] = {
            "tickets": len(s),
            "staked_minor": st,
            "net_minor": sum(t.payout_minor or 0 for t in s) - st,
            "roi": (sum(t.payout_minor or 0 for t in s) - st) / st if st else None,
        }
    return {
        "balance_minor": account.balance_minor,
        "starting_balance_minor": account.starting_balance_minor,
        "reset_count": account.reset_count,
        "tickets": {
            "total": len(tickets),
            "pending": sum(t.status == "pending" for t in tickets),
            "won": sum(t.status == "won" for t in tickets),
            "lost": sum(t.status == "lost" for t in tickets),
            "void": sum(t.status == "void" for t in tickets),
        },
        "settled_staked_minor": staked,
        "settled_returned_minor": returned,
        "net_minor": returned - staked,
        "simulated_roi": (returned - staked) / staked if staked else None,
        "win_rate": (sum(t.status == "won" for t in settled) / len(settled)) if settled else None,
        "average_odds": float(sum(Decimal(t.odds) for t in settled) / len(settled))
        if settled
        else None,
        "mean_model_probability": sum(t.model_probability for t in settled) / len(settled)
        if settled
        else None,
        "max_drawdown": max_drawdown([e.balance_minor for e in ledger]) if ledger else None,
        "by_odds_source": by_source,
        "balance_series": [
            {"at": e.created_at.isoformat(), "balance_minor": e.balance_minor, "kind": e.kind}
            for e in ledger
        ],
        "label": "Simüle edilmiş sonuçlar — gerçek para değildir",
        "disclaimer": DISCLAIMER,
    }
