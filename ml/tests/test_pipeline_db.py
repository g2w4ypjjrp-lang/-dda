"""Eğitim → kayıt → tahmin → değiştirilemezlik → sonuçlandırma (gerçek PostgreSQL, sentetik lig)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from sqlalchemy.orm import Session

from conftest import NOW, future, load_league
from mi_ml.backtest import TrainConfig
from mi_ml.pipeline import predict_scope, scope_key, settle, train_scope
from mi_ml.predict import Thresholds
from synthetic import league_matches

CFG = TrainConfig(n_trials=4, cv_folds=2, window_days=60)


@pytest.fixture
def league(sql: psycopg.Connection[Any]) -> dict[str, int]:
    played = league_matches(n_teams=10, seasons=4)
    last = played[-1].kickoff_at
    upcoming = [
        future(NOW, "T00", "T01", 2, 90_001),
        future(NOW, "T02", "T03", 3, 90_002),
        future(NOW, "T04", "T05", 30, 90_003),  # ufuk dışında (7 gün)
    ]
    assert last < NOW
    return load_league(sql, played + upcoming, fetched_at=NOW - timedelta(minutes=30))


def _train(session: Session, comp: int) -> Any:
    version = train_scope(session, [comp], CFG)
    session.commit()
    return version


def _predict(session: Session, comp: int, **kw: Any) -> list[Any]:
    preds = predict_scope(session, [comp], **kw)
    session.commit()
    return preds


def test_train_registers_champion_then_challenger(
    session: Session, sql: Any, league: dict[str, int]
) -> None:
    comp = league["competition_id"]
    first = _train(session, comp)
    assert first.status == "champion" and first.scope_key == scope_key([comp])
    assert set(first.components) and abs(sum(first.components.values()) - 1) < 1e-9
    assert "dixon_coles" in first.metrics["test"] and "ensemble" in first.metrics["test"]
    assert first.artifact["score_model"]["model"] in ("dixon_coles", "poisson")
    # İY modeli ana modelle aynı test döneminde değerlendirilir; küçük sentetik ligde örneklem
    # yetersiz olduğundan yayımlanmaz ve nedeni kayda geçer.
    fh = first.metrics["first_half"]
    assert fh["method"] == "binomial_thinning" and fh["coverage"] == 1.0
    assert fh["split"]["home"] == pytest.approx(0.45, abs=0.06)
    assert fh["available"] is False and any("örneklem" in r for r in fh["reasons"])
    assert first.artifact["first_half"] == fh
    assert (
        sql.execute(
            "SELECT count(*) FROM ml_tuning_trials WHERE model_version_id=%s", (first.id,)
        ).fetchone()[0]
        == 4
    )
    second = _train(session, comp)
    assert second.status == "challenger"
    assert second.data_fingerprint == first.data_fingerprint  # aynı veri, aynı parmak izi
    # Kapsam başına tek şampiyon: veritabanı kısıtı.
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql.execute("UPDATE ml_model_versions SET status='champion' WHERE id=%s", (second.id,))


def test_predictions_written_immutable_and_deduplicated(
    session: Session, sql: Any, league: dict[str, int]
) -> None:
    comp = league["competition_id"]
    _train(session, comp)
    loose = Thresholds(
        bootstrap=5, min_test_n=10, max_ece=1.0, max_interval_width=1.0, max_disagreement=1.0
    )
    preds = _predict(session, comp, now=NOW, thresholds=loose)
    assert len(preds) == 2  # 30 gün sonraki maç ufuk dışında
    published = [p for p in preds if p.status == "published"]
    assert published, [p.abstain_reasons for p in preds]
    p = published[0]
    x = p.probabilities["1x2"]
    assert abs(x["home"] + x["draw"] + x["away"] - 1) < 1e-9
    # Piyasalar aynı ortak dağılımdan: çifte şans 1X = ev + beraberlik.
    assert abs(p.probabilities["double_chance"]["1X"] - (x["home"] + x["draw"])) < 1e-9
    sm = p.probabilities["score_matrix"]
    assert len(sm) == 11 and abs(sum(map(sum, sm)) - 1) < 1e-4
    # Matristen türetilen 1X2, yayımlanan 1X2 ile tutarlı.
    home = sum(sm[i][j] for i in range(11) for j in range(11) if i > j)
    assert abs(home - x["home"]) < 1e-3
    assert p.uncertainty["method"] == "dixon_coles_bootstrap" and p.uncertainty["samples"] == 5
    assert "güven aralığı değildir" in p.uncertainty["label"]
    assert p.data_snapshot["history_matches"] > 300 and p.features["h_n"] >= 5
    assert p.reliability in ("high", "medium", "low") and p.model_agreement is not None
    assert p.probabilities["first_half"]["available"] is False  # İY doğrulanmadı → yayımlanmaz
    assert p.probabilities["first_half"]["reasons"]

    # Değiştirilemez: güncelleme ve silme reddedilir.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute(
            "UPDATE ml_predictions SET status='abstained', probabilities=NULL WHERE id=%s", (p.id,)
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("DELETE FROM ml_predictions WHERE id=%s", (p.id,))

    # Aynı veriyle tekrar çalıştırma yeni kayıt üretmez.
    assert _predict(session, comp, now=NOW + timedelta(hours=1), thresholds=loose) == []


def test_strict_thresholds_abstain_with_reasons(session: Session, league: dict[str, int]) -> None:
    comp = league["competition_id"]
    _train(session, comp)
    strict = Thresholds(bootstrap=0, min_test_n=10_000)
    preds = _predict(session, comp, now=NOW, thresholds=strict)
    assert all(p.status == "abstained" and p.probabilities is None for p in preds)
    assert all(any(r["code"] == "small_validation" for r in p.abstain_reasons) for p in preds)


def test_prediction_must_precede_kickoff(
    sql: Any, session: Session, league: dict[str, int]
) -> None:
    version = _train(session, league["competition_id"])
    fixture = sql.execute(
        "SELECT id, kickoff_at FROM football_fixtures WHERE external_id='90001'"
    ).fetchone()
    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute(
            "INSERT INTO ml_predictions (fixture_id, model_version_id, created_at, kickoff_at, status, reliability,"
            " features, feature_hash, data_snapshot) VALUES (%s, %s, %s, %s, 'abstained', 'low', '{}', %s, '{}')",
            (fixture[0], version.id, fixture[1] + timedelta(minutes=1), fixture[1], "0" * 64),
        )


def test_no_champion(session: Session, league: dict[str, int]) -> None:
    with pytest.raises(LookupError, match="şampiyon"):
        predict_scope(session, [league["competition_id"]], now=NOW)


def test_settle_once(session: Session, sql: Any, league: dict[str, int]) -> None:
    comp = league["competition_id"]
    _train(session, comp)
    loose = Thresholds(
        bootstrap=0, min_test_n=10, max_ece=1.0, max_interval_width=1.0, max_disagreement=1.0
    )
    _predict(session, comp, now=NOW, thresholds=loose)
    sql.execute(
        "UPDATE football_fixtures SET status='finished', status_detail='FT', home_goals=2, away_goals=0,"
        " ft_home=2, ft_away=0, ht_home=1, ht_away=0 WHERE external_id='90001'"
    )
    assert settle(session, now=NOW + timedelta(days=3)) == 1
    session.commit()
    assert settle(session, now=NOW + timedelta(days=4)) == 0
    session.commit()
    row = sql.execute(
        "SELECT outcome, brier, log_loss, ht_home, ht_away, ht_log_loss FROM ml_prediction_outcomes"
    ).fetchone()
    assert row[0] == "home" and 0 <= row[1] <= 2 and row[2] > 0
    assert (row[3], row[4]) == (1, 0) and row[
        5
    ] is None  # İY skoru kayıtlı; İY tahmini yayımlanmadı
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE ml_prediction_outcomes SET outcome='away'")


def test_predict_active_job_covers_champion_scopes(
    session: Session, sql: Any, league: dict[str, int]
) -> None:
    """Windows tek sunucu kurulumu Celery'siz ``mi-ml predict-active`` çalıştırır."""
    from mi_ml import jobs

    comp = league["competition_id"]
    engine = session.get_bind()
    assert jobs.predict_active(engine, NOW) == {}  # şampiyon yok → yazılacak bir şey yok
    _train(session, comp)  # ilk model kendiliğinden şampiyon
    summary = jobs.predict_active(engine, NOW)
    assert summary[str(comp)]["written"] == 2  # ufuk içindeki 2 maç
    again = jobs.predict_active(engine, NOW)
    assert again[str(comp)]["written"] == 0  # değişmeyen maç yeniden yazılmaz
    assert jobs.settle_all(engine, NOW) == {"settled": 0}  # henüz biten maç yok
