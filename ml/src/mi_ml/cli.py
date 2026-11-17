"""``mi-ml``: eğitim, tahmin ve sonuçlandırma komutları.

    mi-ml train   --competition-id 12 [--competition-id 13] [--trials 100] [--window-days 30]
    mi-ml predict --competition-id 12 [--horizon-days 7] [--bootstrap 30]
    mi-ml settle

Veritabanı adresi ``MI_DATABASE_URL`` ortam değişkeninden (API ile aynı ayarlar).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from mi_api.config import Settings
from mi_api.logs import configure_logging
from mi_api.migrate import sync_url
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mi_ml.backtest import TrainConfig
from mi_ml.pipeline import predict_scope, settle, train_scope
from mi_ml.predict import Thresholds

log = logging.getLogger("mi_ml")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mi-ml")
    sub = parser.add_subparsers(dest="command", required=True)
    tr = sub.add_parser("train", help="Model eğit ve kayıt defterine yaz")
    tr.add_argument("--competition-id", type=int, action="append", required=True)
    tr.add_argument("--trials", type=int, default=100)
    tr.add_argument("--window-days", type=int, default=30)
    tr.add_argument("--min-history", type=int, default=5)
    pr = sub.add_parser("predict", help="Şampiyon modelle yaklaşan maçları tahmin et")
    pr.add_argument("--competition-id", type=int, action="append", required=True)
    pr.add_argument("--horizon-days", type=int, default=7)
    pr.add_argument("--bootstrap", type=int, default=30)
    sub.add_parser("settle", help="Biten maçların tahminlerini sonuçlandır")
    args = parser.parse_args(argv)

    settings = Settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    engine = create_engine(sync_url(settings.database_url.get_secret_value()))
    now = datetime.now(UTC)
    try:
        _run(args, engine, now)
    except (ValueError, LookupError) as exc:
        # Beklenen durumlar (yetersiz veri, şampiyon model yok): iz yığını yerine açık mesaj.
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
    finally:
        engine.dispose()


def _run(args: argparse.Namespace, engine: Any, now: datetime) -> None:
    with Session(engine) as session, session.begin():
        if args.command == "train":
            cfg = TrainConfig(
                n_trials=args.trials, window_days=args.window_days, min_history=args.min_history
            )
            version = train_scope(session, args.competition_id, cfg)
            print(
                json.dumps(
                    {
                        "model_version_id": version.id,
                        "status": version.status,
                        "components": version.components,
                        "excluded": version.excluded,
                        "test_ensemble": {
                            k: version.metrics["test"]["ensemble"][k]
                            for k in ("n", "log_loss", "brier", "ece", "accuracy")
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "predict":
            preds = predict_scope(
                session,
                args.competition_id,
                now=now,
                horizon=timedelta(days=args.horizon_days),
                thresholds=Thresholds(bootstrap=args.bootstrap),
            )
            published = sum(p.status == "published" for p in preds)
            print(
                json.dumps(
                    {
                        "written": len(preds),
                        "published": published,
                        "abstained": len(preds) - published,
                    }
                )
            )
        elif args.command == "settle":
            print(json.dumps({"settled": settle(session, now=now)}))


if __name__ == "__main__":
    main()
