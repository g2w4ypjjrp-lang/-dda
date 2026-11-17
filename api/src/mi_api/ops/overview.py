# ruff: noqa: E501
"""Command Center: platformun tek ekranlık durumu.

Bölümler yöneticinin **okuma izinlerine göre** döner (izin yoksa bölüm hiç gelmez). Değerler
yalnızca gerçek kayıtlardan hesaplanır; kayıt yoksa ``None`` döner (sıfır veya tahmini değer
uydurulmaz). Test modundaki ödemeler gelire katılmaz.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.billing.api import billing_summary
from mi_api.billing.models import Order, Subscription
from mi_api.coupons.models import Coupon
from mi_api.football.api import TR
from mi_api.football.models import Competition, Fixture, SyncRun
from mi_api.models import User, UserSession
from mi_api.predictions.models import ModelVersion, Prediction, PredictionOutcome, TuningTrial
from mi_api.virtual.models import Ticket, VirtualAccount


async def business(db: AsyncSession, now: datetime) -> dict[str, Any]:
    summary = await billing_summary(db, now)
    day_start = now.astimezone(TR).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    live = (Order.test_mode.is_(False), Order.status == "paid")

    async def revenue(since: datetime) -> int | None:
        v = (
            await db.execute(
                select(func.sum(Order.amount_minor)).where(*live, Order.paid_at >= since)
            )
        ).scalar_one()
        return int(v) if v is not None else None

    since30 = now - timedelta(days=30)
    new_subs = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(Subscription.created_at >= since30)
        )
    ).scalar_one()
    canceled = (
        await db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(
                Subscription.status.in_(("canceled", "refunded", "revoked")),
                Subscription.canceled_at >= since30,
            )
        )
    ).scalar_one()
    active = sum(r["count"] for r in summary["active_subscriptions"])
    return {
        "revenue_today_minor": await revenue(day_start),
        "revenue_month_minor": await revenue(month_start),
        "revenue": summary["revenue"],
        "mrr_minor": summary["mrr_minor"],
        "arr_minor": summary["arr_minor"],
        "arpu_30d_minor": summary["arpu_30d_minor"],
        "churn_30d": summary["churn_30d"],
        "active_subscriptions": active,
        "new_subscriptions_30d": new_subs,
        "canceled_30d": canceled,
        "orders_in_review": summary["orders_in_review"],
        "costs": {"api": None, "server": None},
        "note": summary["note"] + " Maliyet verisi bağlı değil.",
    }


async def users(db: AsyncSession, now: datetime) -> dict[str, Any]:
    by_status = dict(
        (await db.execute(select(User.status, func.count()).group_by(User.status))).all()
    )
    total = sum(by_status.values())
    new7 = (
        await db.execute(
            select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=7))
        )
    ).scalar_one()
    active30 = (
        await db.execute(
            select(func.count(distinct(UserSession.user_id))).where(
                UserSession.last_seen_at >= now - timedelta(days=30)
            )
        )
    ).scalar_one()
    paid = dict(
        (
            await db.execute(
                select(Subscription.plan_code, func.count(distinct(Subscription.user_id)))
                .where(
                    Subscription.status.in_(("active", "canceled")),
                    Subscription.started_at <= now,
                    Subscription.current_period_end > now,
                )
                .group_by(Subscription.plan_code)
            )
        ).all()
    )
    return {
        "total": total,
        "active_30d": active30,
        "new_7d": new7,
        "suspended": by_status.get("suspended", 0),
        "plans": {
            "FREE": max(0, by_status.get("active", 0) - sum(paid.values())),
            "PRO": paid.get("PRO", 0),
            "ELITE": paid.get("ELITE", 0),
        },
    }


async def football(db: AsyncSession, now: datetime) -> dict[str, Any]:
    start = now.astimezone(TR).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    today = dict(
        (
            await db.execute(
                select(Fixture.status, func.count())
                .where(Fixture.kickoff_at >= start, Fixture.kickoff_at < end)
                .group_by(Fixture.status)
            )
        ).all()
    )
    upcoming = (
        await db.execute(
            select(func.count())
            .select_from(Fixture)
            .where(
                Fixture.status.in_(("scheduled", "tbd")),
                Fixture.kickoff_at > now,
                Fixture.kickoff_at <= now + timedelta(days=7),
            )
        )
    ).scalar_one()
    postponed = (
        await db.execute(
            select(func.count())
            .select_from(Fixture)
            .where(Fixture.status == "postponed", Fixture.kickoff_at >= now - timedelta(days=7))
        )
    ).scalar_one()
    leagues = (
        await db.execute(select(func.count()).select_from(Competition).where(Competition.is_active))
    ).scalar_one()
    last = (
        await db.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
    ).scalar_one_or_none()
    failed24 = (
        await db.execute(
            select(func.count())
            .select_from(SyncRun)
            .where(SyncRun.status == "failed", SyncRun.started_at >= now - timedelta(hours=24))
        )
    ).scalar_one()
    return {
        "today": sum(today.values()),
        "live": today.get("live", 0) + today.get("halftime", 0),
        "finished_today": today.get("finished", 0),
        "upcoming_7d": upcoming,
        "postponed_7d": postponed,
        "active_leagues": leagues,
        "last_sync": {"job": last.job, "status": last.status, "at": last.started_at.isoformat()}
        if last
        else None,
        "failed_syncs_24h": failed24,
    }


async def ai(db: AsyncSession, now: datetime) -> dict[str, Any]:
    champions = (
        (await db.execute(select(ModelVersion).where(ModelVersion.status == "champion")))
        .scalars()
        .all()
    )
    since = now - timedelta(days=30)
    preds = dict(
        (
            await db.execute(
                select(Prediction.status, func.count())
                .where(Prediction.created_at >= since)
                .group_by(Prediction.status)
            )
        ).all()
    )
    settled = (
        await db.execute(
            select(
                func.count(),
                func.avg(PredictionOutcome.brier),
                func.avg(PredictionOutcome.log_loss),
            )
            .join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
            .where(Prediction.status == "published", PredictionOutcome.settled_at >= since)
        )
    ).one()
    trials = (await db.execute(select(func.count()).select_from(TuningTrial))).scalar_one()
    last_train = (await db.execute(select(func.max(ModelVersion.created_at)))).scalar_one()
    drift = []
    for v in champions:
        test = (v.metrics or {}).get("test", {}).get("ensemble", {})
        live = (
            await db.execute(
                select(func.count(), func.avg(PredictionOutcome.log_loss))
                .join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
                .where(
                    Prediction.model_version_id == v.id,
                    Prediction.status == "published",
                    PredictionOutcome.settled_at >= since,
                )
            )
        ).one()
        n, ll = int(live[0]), live[1]
        if (
            n >= 50
            and test.get("log_loss") is not None
            and ll is not None
            and ll > test["log_loss"] + 0.05
        ):
            drift.append(
                {
                    "model_version_id": v.id,
                    "scope_key": v.scope_key,
                    "n": n,
                    "live_log_loss": float(ll),
                    "test_log_loss": test["log_loss"],
                }
            )
    n_settled = int(settled[0])
    return {
        "champions": [
            {
                "id": v.id,
                "scope_key": v.scope_key,
                "trained_until": v.trained_until.isoformat(),
                "test": {
                    k: (v.metrics or {}).get("test", {}).get("ensemble", {}).get(k)
                    for k in ("n", "log_loss", "brier", "ece")
                },
            }
            for v in champions
        ],
        "predictions_30d": {
            "published": preds.get("published", 0),
            "abstained": preds.get("abstained", 0),
        },
        "settled_30d": {
            "n": n_settled,
            "brier": float(settled[1]) if n_settled else None,
            "log_loss": float(settled[2]) if n_settled else None,
            "uniform_log_loss": math.log(3),
        },
        "optuna_trials": trials,
        "last_training_at": last_train.isoformat() if last_train else None,
        "drift": drift,
        "drift_rule": "Son 30 günde ≥50 sonuçlanmış tahminde canlı log loss, test log loss'tan 0.05'ten fazla kötüyse uyarı",
    }


async def coupons(db: AsyncSession, now: datetime) -> dict[str, Any]:
    counts = dict(
        (await db.execute(select(Coupon.status, func.count()).group_by(Coupon.status))).all()
    )
    settled = (
        await db.execute(
            select(
                func.count(),
                func.avg(Coupon.joint_probability),
                func.avg(case((Coupon.status == "won", 1.0), else_=0.0)),
            ).where(Coupon.status.in_(("won", "lost")))
        )
    ).one()
    n = int(settled[0])
    return {
        "total": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "won": counts.get("won", 0),
        "lost": counts.get("lost", 0),
        "void": counts.get("void", 0),
        "created_7d": (
            await db.execute(
                select(func.count())
                .select_from(Coupon)
                .where(Coupon.created_at >= now - timedelta(days=7))
            )
        ).scalar_one(),
        "realized": {
            "n": n,
            "mean_predicted": float(settled[1]),
            "observed_win_rate": float(settled[2]),
        }
        if n
        else None,
    }


async def virtual(db: AsyncSession, now: datetime) -> dict[str, Any]:
    accounts, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(VirtualAccount.balance_minor), 0))
        )
    ).one()
    tickets = dict(
        (await db.execute(select(Ticket.status, func.count()).group_by(Ticket.status))).all()
    )
    staked, returned = (
        await db.execute(
            select(
                func.coalesce(func.sum(Ticket.stake_minor), 0),
                func.coalesce(func.sum(Ticket.payout_minor), 0),
            ).where(Ticket.status.in_(("won", "lost")))
        )
    ).one()
    active = (
        await db.execute(
            select(func.count(distinct(Ticket.account_id))).where(
                Ticket.created_at >= now - timedelta(days=30)
            )
        )
    ).scalar_one()
    return {
        "accounts": int(accounts),
        "active_30d": active,
        "total_balance_minor": int(total),
        "tickets": sum(tickets.values()),
        "pending_tickets": tickets.get("pending", 0),
        "simulated_roi": round((int(returned or 0) - int(staked or 0)) / int(staked), 4)
        if staked
        else None,
        "label": "Simüle edilmiş — gerçek para değildir",
    }


SECTIONS = {
    "business": ("finance.read", business),
    "users": ("users.read", users),
    "football": ("football.read", football),
    "ai": ("models.read", ai),
    "coupons": ("coupons.read", coupons),
    "virtual": ("virtual.read", virtual),
}
