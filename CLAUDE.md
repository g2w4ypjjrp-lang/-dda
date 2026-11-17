# Match Intelligence AI — çalışma notları

Futbol istihbarat ve analitik SaaS platformu. Ürün analiz + **sanal** simülasyon sunar; gerçek bahis
yapmaz, kazanç garantisi vermez. Arayüz ve belgeler Türkçe.

Önce oku: `docs/01-yol-haritasi.md` (fazlar ve onay kapıları), ardından son faz raporları (`docs/0*-raporu.md`).

## Yapı

* `api/` — FastAPI, SQLAlchemy 2 (async), Alembic (elle yazılmış SQL geçişleri), PostgreSQL 16, Redis 7, Celery işçisi (`mi_api.worker`)
* `ml/` — tahmin motoru (`mi_ml`): Poisson, Dixon-Coles, Elo, LightGBM + Optuna, değerlendirme, tahmin hattı; `mi-ml` CLI
* `web/` — Next.js 16, TypeScript strict, Tailwind 4, TanStack Query; API'yi `/v1` ve `/admin/v1` üzerinden aynı köken olarak vekil eder

## Kurallar (projenin ilkeleri)

* Gerçek olmayan veri, metrik, kullanıcı veya kazanç **gösterilmez**. Veri yoksa "veri yok" denir.
  Demo verisi yalnızca `MI_ENVIRONMENT=development|test` ortamında (`ml/scripts/seed_demo.py`).
* Tahmin olasılığı, model güvenilirliği, veri kalitesi ve belirsizlik ayrı gösterilir; yetersiz
  durumda çekimser kalınır ve nedeni söylenir.
* Tahminler maçtan önce yazılır ve değiştirilemez (veritabanı tetikleyicisi). Denetim kaydı hash zincirlidir.
* Yetki kontrolü her zaman backend'de (`require_permission`); hassas izinler yeniden doğrulama ister.
* Onay kapıları (M-G1…M-G6: veri sağlayıcı, oran verisi, dağıtım, hukuk, canlı ödeme, e-posta)
  kullanıcı onayı olmadan geçilmez.
* Her faz: kod + gerçek testler + `docs/` altında rapor. Başarısız test gizlenmez.
* Commit mesajları Türkçe.

## Komutlar

```bash
# Hizmetler: PostgreSQL 16 + Redis 7 (en kolayı Docker Desktop)
docker compose up -d postgres redis      # .env.example → .env (MI_DB_PASSWORD, MI_SECRET_KEK)

# API
cd api && uv sync
MI_TEST_DATABASE_URL=postgresql://<kullanıcı>:<parola>@127.0.0.1:5432/<db> MI_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run mi-admin migrate && uv run mi-api --port 8080

# ML
cd ml && uv sync && MI_TEST_DATABASE_URL=... uv run pytest && uv run mypy
MI_ENVIRONMENT=test uv run python scripts/seed_demo.py     # yalnızca test/geliştirme verisi

# Web
cd web && npm ci && npm run typecheck && npm run build
npm run dev                                                # http://localhost:3000 (MI_API_URL=http://127.0.0.1:8080)
E2E_API_DIR=../api npx playwright test                     # temiz + demo verili DB gerekir: e2e/reset-local.sh
```

Windows'ta PowerShell ortam değişkeni örneği: `$env:MI_DATABASE_URL = "postgresql://..."`.

## Sıradaki iş

Faz 4 (kupon motoru) tamamlandı: `docs/06-faz4-raporu.md`. Sıradakiler:
1. İlk yarı skor modeli ve İY piyasaları; maç sayfasından "kupona ekle".
2. Faz 5 — sanal bakiye: çift kayıtlı defter (çekilemez, transfer edilemez), sabit tutar / yüzde /
   kesirli Kelly (oran yoksa Kelly uygulanamaz), günlük risk ve işlem sınırı, drawdown, simüle ROI.
   Kayıp kovalamayı teşvik eden özellik yok; sanal sonuç gerçek kazanç gibi gösterilmez.
