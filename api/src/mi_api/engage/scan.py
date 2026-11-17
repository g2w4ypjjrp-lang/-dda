# ruff: noqa: E501
"""Periyodik bildirim taraması (Celery ``mi.notifications.scan``, 5 dakikada bir).

* Favori takımı/maçı olan kullanıcılara: maç 60 dakika içinde başlıyor; maç bitti (90' skoru).
* Aboneliği 3 gün içinde bitecek ve aynı paketi uzatmamış kullanıcılara hatırlatma.
Her olay ``dedupe_key`` ile bir kez gönderilir; iş tekrar çalışsa da çoğaltmaz.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mi_api.billing.models import Subscription
from mi_api.engage.models import Favorite
from mi_api.engage.notify import notify
from mi_api.football.api import TR
from mi_api.football.models import Fixture, Team

Home = aliased(Team)
Away = aliased(Team)


async def _fans(db: AsyncSession, fx: Fixture) -> set:  # type: ignore[type-arg]
    rows = await db.execute(
        select(Favorite.user_id).where(
            or_(
                and_(Favorite.kind == "fixture", Favorite.ref_id == fx.id),
                and_(
                    Favorite.kind == "team", Favorite.ref_id.in_((fx.home_team_id, fx.away_team_id))
                ),
            )
        )
    )
    return set(rows.scalars())


async def scan(db: AsyncSession, now: datetime) -> dict[str, int]:
    sent = {"match": 0, "result": 0, "subscription": 0}
    q = (
        select(Fixture, Home.name, Away.name)
        .join(Home, Home.id == Fixture.home_team_id)
        .join(Away, Away.id == Fixture.away_team_id)
    )
    upcoming = (
        await db.execute(
            q.where(
                Fixture.status.in_(("scheduled", "tbd")),
                Fixture.kickoff_at > now,
                Fixture.kickoff_at <= now + timedelta(minutes=60),
            )
        )
    ).all()
    for fx, h, a in upcoming:
        local = fx.kickoff_at.astimezone(TR).strftime("%H:%M")
        for uid in await _fans(db, fx):
            if await notify(
                db,
                uid,
                "match",
                f"{h} – {a} başlıyor",
                f"Maç {local}'da başlıyor. AI analizi maç sayfasında.",
                now=now,
                link=f"/maclar/{fx.id}",
                dedupe_key=f"match:{fx.id}",
            ):
                sent["match"] += 1
    finished = (
        await db.execute(
            q.where(Fixture.status == "finished", Fixture.kickoff_at >= now - timedelta(hours=24))
        )
    ).all()
    for fx, h, a in finished:
        hg = fx.ft_home if fx.ft_home is not None else fx.home_goals
        ag = fx.ft_away if fx.ft_away is not None else fx.away_goals
        if hg is None or ag is None:
            continue
        for uid in await _fans(db, fx):
            if await notify(
                db,
                uid,
                "result",
                f"Maç bitti: {h} {hg}–{ag} {a}",
                "Model tahmini ve sonucu maç sayfasında karşılaştırabilirsiniz.",
                now=now,
                link=f"/maclar/{fx.id}",
                dedupe_key=f"result:{fx.id}",
            ):
                sent["result"] += 1
    later = aliased(Subscription)
    expiring = (
        (
            await db.execute(
                select(Subscription).where(
                    Subscription.status == "active",
                    Subscription.current_period_end > now,
                    Subscription.current_period_end <= now + timedelta(days=3),
                    ~select(later.id)
                    .where(
                        later.user_id == Subscription.user_id,
                        later.plan_code == Subscription.plan_code,
                        later.status == "active",
                        later.started_at >= Subscription.current_period_end,
                    )
                    .exists(),
                )
            )
        )
        .scalars()
        .all()
    )
    for s in expiring:
        end = s.current_period_end.astimezone(TR).strftime("%d.%m.%Y")
        if await notify(
            db,
            s.user_id,
            "subscription",
            f"{s.plan_code} paketiniz {end} tarihinde bitiyor",
            "Otomatik yenileme yoktur; devam etmek için Paketler sayfasından süreyi uzatabilirsiniz.",
            now=now,
            link="/paketler",
            dedupe_key=f"expiring:{s.id}",
        ):
            sent["subscription"] += 1
    return sent
