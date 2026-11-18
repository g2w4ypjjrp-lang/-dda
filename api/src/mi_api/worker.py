"""Celery işçisi ve zamanlanmış futbol verisi işleri (Celery Beat).

Çalıştırma::

    celery -A mi_api.worker worker --loglevel=INFO --concurrency=2
    celery -A mi_api.worker beat --loglevel=INFO

Program, verinin türüne göre yenileme sıklığını ayarlar. Her iş kota bütçesinden geçer;
bütçe dolarsa düşük öncelikli işler atlanır (``football_sync_runs``'ta "skipped" görünür).
Aynı iş aynı anda iki kez çalışmaz (Redis kilidi).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from celery import Celery, signals
from celery.schedules import crontab
from redis import Redis as SyncRedis

from mi_api import aio, jobs
from mi_api.config import Settings
from mi_api.football.sync import Job
from mi_api.jobs import run_job
from mi_api.logs import configure_logging

_settings = Settings()
_broker = _settings.redis_url.get_secret_value() if _settings.redis_url else "memory://"

app = Celery("mi", broker=_broker)
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Bugün ve yarının fikstürü (UTC günleri; Türkiye günü iki UTC gününe yayılır).
        "fixtures-today": {
            "task": "mi.football.sync",
            "schedule": 600.0,
            "args": ("fixtures_date", {"offset_days": 0}),
        },
        "fixtures-tomorrow": {
            "task": "mi.football.sync",
            "schedule": 3600.0,
            "args": ("fixtures_date", {"offset_days": 1}),
        },
        "fixtures-yesterday": {
            "task": "mi.football.sync",
            "schedule": 3600.0,
            "args": ("fixtures_date", {"offset_days": -1}),
        },
        # Canlı: veritabanında canlı/başlamak üzere maç yoksa istek atmadan atlanır.
        "live": {"task": "mi.football.sync", "schedule": 60.0, "args": ("live", {})},
        "upcoming-details": {
            "task": "mi.football.sync",
            "schedule": 900.0,
            "args": ("upcoming_details", {}),
        },
        # Kupon sonuçlandırma: biten maçların seçimleri ve kuponların durumu.
        "coupons-settle": {"task": "mi.coupons.settle", "schedule": 900.0},
        # Kalp atışı: zamanlayıcı (beat) planlar, işçi çalıştırır; System Health ikisini de izler.
        "heartbeat": {"task": "mi.heartbeat", "schedule": 60.0},
        # Favori maç başlıyor/bitti ve abonelik bitiyor bildirimleri (tekrarsız).
        "notifications-scan": {"task": "mi.notifications.scan", "schedule": 300.0},
        # Günlük yedek (03:17 UTC) + geçici veritabanına geri yükleyerek doğrulama.
        "backup-daily": {"task": "mi.backup", "schedule": crontab(hour=3, minute=17)},
        "standings": {
            "task": "mi.football.sync",
            "schedule": 6 * 3600.0,
            "args": ("standings_active", {}),
        },
    },
)

if _settings.ml_schedule_enabled:
    app.conf.beat_schedule.update(
        {
            # Şampiyon modelli kapsamlar, 7 günlük ufuk; değişmeyen maç yeniden yazılmaz.
            "ml-predict": {
                "task": "mi.ml.predict_active",
                "schedule": 1800.0,
                "options": {"queue": "ml"},
            },
            "ml-settle": {"task": "mi.ml.settle", "schedule": 3600.0, "options": {"queue": "ml"}},
        }
    )


@signals.setup_logging.connect  # type: ignore[untyped-decorator]
def _setup_logging(**_: Any) -> None:
    """Celery kendi log ayarını yapmasın; uygulamanın JSON + maskeleme ayarı kullanılsın."""
    configure_logging(_settings.log_level, json_output=_settings.log_json)


@app.task(name="mi.football.sync")  # type: ignore[untyped-decorator]
def football_sync(job: Job, params: dict[str, Any]) -> dict[str, Any]:
    lock_key = f"mi:lock:football:{job}:{sorted(params.items())}"
    redis = SyncRedis.from_url(_broker) if _settings.redis_url else None
    lock = redis.lock(lock_key, timeout=900, blocking=False) if redis else None
    if lock is not None and not lock.acquire(blocking=False):
        return {"job": job, "status": "skipped", "message": "Aynı iş zaten çalışıyor"}
    try:
        return aio.run(run_job(job, dict(params)))
    finally:
        if lock is not None:
            lock.release()


@app.task(name="mi.coupons.settle")  # type: ignore[untyped-decorator]
def coupons_settle() -> dict[str, int]:
    return aio.run(jobs.settle_coupons())


HEARTBEAT_KEY = "mi:heartbeat:worker"


@app.task(name="mi.backup")  # type: ignore[untyped-decorator]
def backup_daily() -> dict[str, Any]:
    return aio.run(jobs.daily_backup(_settings))


@app.task(name="mi.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> str:
    now = datetime.now(UTC).isoformat()
    if _settings.redis_url:
        SyncRedis.from_url(_settings.redis_url.get_secret_value()).set(HEARTBEAT_KEY, now, ex=900)
    return now


@app.task(name="mi.notifications.scan")  # type: ignore[untyped-decorator]
def notifications_scan() -> dict[str, int]:
    return aio.run(jobs.scan_notifications())
