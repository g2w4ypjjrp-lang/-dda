"""Demo / test ortamı verisi: kurgusal lig + model eğitimi + tahminler.

YALNIZCA ``MI_ENVIRONMENT`` development veya test iken çalışır; staging/production'da reddeder.
Kaynak adı ``demo`` olarak yazılır ve arayüzde "Demo verisi (test ortamı — gerçek değil)" görünür.
Takımlar "Demo ..." adlıdır; skorlar bilinen parametrelerden rastgele üretilir (gerçek değildir).

Kullanım (E2E ve yerel görsel kontrol):
    MI_DATABASE_URL=... MI_ENVIRONMENT=test uv run python scripts/seed_demo.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import psycopg
from mi_api.config import Settings

from mi_ml.backtest import TrainConfig
from mi_ml.pipeline import predict_scope, train_scope
from mi_ml.scores import ScoreMatrix

SEASONS = 10
TEAMS = [
    "Demo Kartallar", "Demo Aslanlar", "Demo Yıldızlar", "Demo Fırtına", "Demo Liman", "Demo Kuzey",
    "Demo Vadi", "Demo Şimşek", "Demo Rüzgâr", "Demo Kale", "Demo Ateş", "Demo Dağlar",
]  # fmt: skip


def main() -> None:
    settings = Settings()
    if settings.environment not in ("development", "test"):
        sys.exit("Demo verisi yalnızca development/test ortamında yüklenebilir.")
    dsn = settings.database_url.get_secret_value()
    rng = np.random.default_rng(2026)
    attack = rng.normal(0, 0.3, len(TEAMS))
    defence = rng.normal(0, 0.25, len(TEAMS))
    attack -= attack.mean()
    defence -= defence.mean()
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    tr_midnight = datetime.now(ZoneInfo("Europe/Istanbul")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    def sample(h: int, a: int) -> tuple[int, int, int, int]:
        lam = float(np.exp(0.15 + attack[h] + defence[a] + 0.28))
        mu = float(np.exp(0.15 + attack[a] + defence[h]))
        m = ScoreMatrix.from_rates(lam, mu, -0.08)
        x, y = np.unravel_index(rng.choice(m.probs.size, p=m.probs.ravel()), m.probs.shape)
        hx = int(rng.binomial(int(x), 0.45))
        hy = int(rng.binomial(int(y), 0.45))
        return int(x), int(y), hx, hy

    with psycopg.connect(dsn, autocommit=True) as sql:
        if sql.execute(
            "SELECT count(*) FROM football_competitions WHERE provider='demo'"
        ).fetchone()[0]:
            sys.exit("Demo verisi zaten yüklü.")
        country = sql.execute(
            "INSERT INTO football_countries (name, code) VALUES ('Demo Ülkesi', 'DMO') ON CONFLICT (name) DO UPDATE SET code=EXCLUDED.code RETURNING id"
        ).fetchone()[0]
        comp = sql.execute(
            "INSERT INTO football_competitions (provider, external_id, name, country_id, is_active, fetched_at)"
            " VALUES ('demo', 'L1', 'Demo Süper Lig', %s, true, %s) RETURNING id",
            (country, now),
        ).fetchone()[0]
        team_ids = [
            sql.execute(
                "INSERT INTO football_teams (provider, external_id, name, country_id, fetched_at) VALUES ('demo', %s, %s, %s, %s) RETURNING id",
                (f"T{i}", name, country, now),
            ).fetchone()[0]
            for i, name in enumerate(TEAMS)
        ]
        venue = sql.execute(
            "INSERT INTO football_venues (provider, external_id, name, city, fetched_at) VALUES ('demo','V1','Demo Arena','Demo Şehir',%s) RETURNING id",
            (now,),
        ).fetchone()[0]
        seasons: dict[int, int] = {}
        fid = 0

        def season_id(year: int) -> int:
            if year not in seasons:
                seasons[year] = sql.execute(
                    "INSERT INTO football_seasons (competition_id, year, label, is_current) VALUES (%s, %s, %s, %s) RETURNING id",
                    (
                        comp,
                        year,
                        f"{year}/{(year + 1) % 100:02d}",
                        year == now.year - (0 if now.month >= 7 else 1),
                    ),
                ).fetchone()[0]
            return seasons[year]

        def insert(
            kickoff: datetime,
            h: int,
            a: int,
            status: str,
            detail: str,
            score: tuple[int, int, int, int] | None,
            minute: int | None = None,
        ) -> int:
            nonlocal fid
            fid += 1
            year = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
            gh, ga, hh, ha = score if score else (None, None, None, None)
            final = status == "finished"
            return sql.execute(
                "INSERT INTO football_fixtures (provider, external_id, season_id, round, kickoff_at, status, status_detail, minute,"
                " home_team_id, away_team_id, venue_id, referee, home_goals, away_goals, ht_home, ht_away, ft_home, ft_away, fetched_at)"
                " VALUES ('demo', %s, %s, 'Demo Hafta', %s, %s, %s, %s, %s, %s, %s, 'Demo Hakem', %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    str(fid),
                    season_id(year),
                    kickoff,
                    status,
                    detail,
                    minute,
                    team_ids[h],
                    team_ids[a],
                    venue,
                    gh,
                    ga,
                    hh if status != "live" or (minute or 0) > 45 else None,
                    ha if status != "live" or (minute or 0) > 45 else None,
                    gh if final else None,
                    ga if final else None,
                    now,
                ),
            ).fetchone()[0]

        # 10 sezonluk geçmiş (her sezon çift devre), bugünden önce biter.
        n = len(TEAMS)
        start = tr_midnight - timedelta(days=SEASONS * 300 + 10)
        for s in range(SEASONS):
            pairs = [(h, a) for h in range(n) for a in range(n) if h != a]
            rng.shuffle(pairs)
            for i, (h, a) in enumerate(pairs):
                kickoff = start + timedelta(days=300 * s, hours=40 * i)
                insert(kickoff.astimezone(UTC), h, a, "finished", "FT", sample(h, a))

        # Bugün: 2 bitmiş (istatistikli), 1 canlı, 3 yaklaşan; yarın: 3 yaklaşan.
        # Türkiye saatiyle geç saatte (18:00 sonrası) "bugün" yaklaşan maça yer kalmaz; o zaman
        # yaklaşan maçlar yarın ve ertesi gün öğleden sonraya konur (yarın: tahmini yayımlanan
        # üçlü; kupon testleri "Yarın"ı dener). Testler saatten bağımsız olsun diye.
        if datetime.now(ZoneInfo("Europe/Istanbul")).hour < 18:
            soon = [now + timedelta(hours=h) for h in (2, 3, 4)]
            later = [now + timedelta(days=1, hours=h) for h in (1, 2, 3)]
        else:
            soon = [
                (tr_midnight + timedelta(days=2, hours=h)).astimezone(UTC) for h in (15, 16, 17)
            ]
            later = [
                (tr_midnight + timedelta(days=1, hours=h)).astimezone(UTC) for h in (15, 16, 17)
            ]
        today = [
            (now - timedelta(hours=5), 0, 1, "finished"), (now - timedelta(hours=3), 2, 3, "finished"),
            (now - timedelta(minutes=55), 4, 5, "live"),
            (soon[0], 6, 7, "scheduled"), (soon[1], 8, 9, "scheduled"), (soon[2], 10, 11, "scheduled"),
            (later[0], 1, 0, "scheduled"), (later[1], 3, 2, "scheduled"), (later[2], 5, 4, "scheduled"),
        ]  # fmt: skip
        for kickoff, h, a, status in today:
            score = sample(h, a) if status != "scheduled" else None
            if status == "live" and score:
                score = (min(score[0], 2), min(score[1], 1), score[2], score[3])
            fx = insert(
                kickoff,
                h,
                a,
                status,
                {"finished": "FT", "live": "2H", "scheduled": "NS"}[status],
                score,
                57 if status == "live" else None,
            )
            if status == "finished":
                for team, xg, shots, poss in (
                    (team_ids[h], 1.62, 15, 56),
                    (team_ids[a], 0.88, 9, 44),
                ):
                    sql.execute(
                        "INSERT INTO football_fixture_team_stats (fixture_id, team_id, shots_total, shots_on_target, possession_pct, corners,"
                        " fouls, yellow_cards, red_cards, passes_total, passes_accurate, xg, provider, fetched_at)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,'demo',%s)",
                        (fx, team, shots, shots // 3, poss, 5, 11, 2, 420, 350, xg, now),
                    )
        sql.execute(
            "INSERT INTO football_provider_status (provider, last_success_at) VALUES ('demo', %s) ON CONFLICT (provider) DO UPDATE SET last_success_at = EXCLUDED.last_success_at",
            (now,),
        )
        sql.execute(
            "INSERT INTO football_sync_runs (provider, job, params, trigger, status, started_at, finished_at, requests, items, message)"
            " VALUES ('demo', 'fixtures_date', %s, 'cli', 'succeeded', %s, %s, 0, %s, 'Demo verisi yüklendi')",
            (json.dumps({"date": now.date().isoformat()}), now, now, fid),
        )

    from mi_api.migrate import sync_url
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(sync_url(dsn))
    with Session(engine) as session, session.begin():
        version = train_scope(session, [comp], TrainConfig(n_trials=8, cv_folds=2, window_days=60))
        version_id = version.id
        test = {k: version.metrics["test"]["ensemble"][k] for k in ("n", "log_loss", "ece")}
    with Session(engine) as session, session.begin():
        preds = predict_scope(session, [comp], now=datetime.now(UTC), horizon=timedelta(days=3))
        n_preds, n_published = len(preds), sum(p.status == "published" for p in preds)
    engine.dispose()
    print(
        json.dumps(
            {
                "competition_id": comp,
                "fixtures": fid,
                "model_version_id": version_id,
                "test_ensemble": test,
                "predictions": n_preds,
                "published": n_published,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
