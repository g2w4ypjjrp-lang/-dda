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

Faz 4 (kupon), Faz 5 (sanal portföy) ve Faz 6 (paketler, ödeme, lisans) tamamlandı:
`docs/06-faz4-raporu.md`, `docs/07-faz5-raporu.md`, `docs/08-faz6-raporu.md`; ilk yarı modeli ve
"kupona ekle": `docs/09-ilk-yari-raporu.md` (İY piyasaları yalnızca `halftime.evaluate` kapısından
geçerse yayımlanır; demo verisinde geçmiyor — eşiği demo için gevşetmeyin). Faz 8 tasarımlar:
`docs/10-faz8-raporu.md` — yapılandırma katı şemadan geçer (CSS'e yalnızca hex/sayı/izinli seçenek),
web `lib/design.ts` + `components/design.tsx` (`useLayout()`); yeni varyant = şema + defaults +
`designAttrs`/CSS + bileşen. Faz 9 yönetim: `docs/11-faz9-raporu.md` — `mi_api/ops/` (overview, health,
actions, explorer, flags); yeni Data Explorer varlığı yalnızca beyaz listeye açık sütunla eklenir.
Faz 7 kalanları: `docs/12-faz7-raporu.md` — `mi_api/engage/` (bildirim için `notify(..., dedupe_key=)`,
güvenlik kategorisi kapatılamaz); panel bileşeni = `WIDGETS` (API) + `components/widgets.tsx`.
Paket hakları `mi_api.billing.plans` ile **backend'de** kontrol edilir; yeni bir ücretli özellik
eklerken `plan_entitlements` anahtarı + `ENTITLEMENTS` tipi + `LOCK_LABELS` + geçişte tohum değeri ekleyin.
Testlerde ücretli kullanıcı: `conftest.member(...)`; E2E'de `e2e/support.ts` → `grantPlan`.
Canlı ödeme (M-G5) kullanıcı onayı olmadan açılmaz.

Faz 10 (yayın öncesi): `docs/13-faz10-raporu.md`, üretim: `docs/calistirma-kilavuzu.md`.
Dört göz: kritik işlem eklerken `mi_api/ops/approvals.py` → `ACTIONS` yürütücüsü + uçta `approvals.submit`
(202 döner; web'de `ApprovalSent`). Yedek: `mi_api/ops/backup.py` + `mi-admin backup/backup-verify/restore`.
Yeni rota eklerken `tests/test_security_sweep.py` otomatik kapsar; herkese açık rota bilinçli olarak
`PUBLIC` listesine eklenmeli. `/metrics` jetonla (`MI_METRICS_TOKEN`).
Erişilebilirlik: E2E her koşuda axe ile WCAG 2.1 AA denetler (`e2e/a11y.ts` → `expectAccessible`);
tasarım renkleri `design/contrast.py` (web: `lib/contrast.ts`) eşiğini geçmeden yayımlanamaz; vurgu
tonlu zemine `tone-highlight` sınıfı verin. Anahtar döndürme: `mi-admin rotate-kek`.

Dağıtım kararı (M-G3, kullanıcı): `futbol.canarslan.net.tr`, kullanıcının mevcut **Windows 11 VDS**'sinde
(sanallaştırma kapalı → Docker yok; 6 GB bellek, bot `ati-engine` ve Caddy `C:\ATI\...` aynı makinede),
`C:\Kurulum\Futbol` altında, bottan AYRIK — `deploy/windows/` + `docs/windows-kurulum.md`. Tek sunucu modu
(`MI_SINGLE_SERVER=true`): Redis/Celery yok, işler `mi_api/scheduler.py` ile API içinde; Windows'ta olay döngüsü
`mi_api/aio.py` (psycopg Proactor'la çalışmaz). Portlar: web 3080, API 8081, PostgreSQL 5433 (yalnızca 127.0.0.1);
web önceden derlenip gönderilir (`MI_API_URL=http://127.0.0.1:8081`). Caddy'ye işaretli blok `caddy-ekle.ps1` ile.
Linux sunucu için `deploy/vds/` (Docker) de hazır ve test edildi.

Sıradakiler (kullanıcı kararı bekleyenler): M-G1 veri sağlayıcı, M-G2 oran verisi, M-G3 Windows kurulumunun
sunucuda uygulanması (kullanıcı adım adım çalıştırıyor), M-G4 hukuk metinleri, M-G5 canlı ödeme, M-G6 e-posta. Ayrıntı: `docs/13-faz10-raporu.md` §Açık kalanlar.

Varsayılan tasarım `neon-light` (kullanıcı kararı; geçiş 0014, `docs/14-neon-kupon-raporu.md`): açık zemin, neon
yalnızca süs (`shadow: "neon"`, ev/deplasman renkleri) — metin renkleri kontrast kapısından geçmeli. Ana menü 4 başlık
(Ana Sayfa, Tahminler, Kupon Oluştur, Başarı Oranı). Kupon üretme `days` (1–7) penceresi; güvenilirlik eşikleri gevşetilmez.
Sunucuda: `futbol.ps1 parola EPOSTA [-MfaSifirla]`, `futbol.ps1 paket EPOSTA`, `futbol.ps1 model-durum`.

Kod saklama: kullanıcı her faz sonunda ZIP ister; GitHub'a yalnızca istediğinde yüklenir.
