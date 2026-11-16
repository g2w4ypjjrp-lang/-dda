# Faz 1 Raporu — Teknik Temel

> Durum: **Tamamlandı (kod + otomatik testler).** Üretim dağıtımı M-G3, e-posta gönderimi M-G6 ile.

## 1. Tamamlanan işler

| Alan | Uygulama |
|---|---|
| Mimari | `api/`: FastAPI + SQLAlchemy 2 (async, psycopg3) + Alembic + PostgreSQL 16 + Redis 7. Uygulama fabrikası, ayarlar (`MI_` önekli), tek biçimli hata yanıtı `{code, detail}` |
| Veritabanı | Alembic geçişi `0001`: 10 tablo + 1 görünüm + tetikleyiciler; CHECK kısıtlarıyla veritabanı düzeyinde güvence |
| Kimlik doğrulama | Kayıt, e-posta doğrulama, giriş/çıkış, parola sıfırlama/değiştirme, oturum listesi ve kapatma, hesap silme (KVKK anonimleştirme) |
| MFA | TOTP (RFC 6238) + 10 tek kullanımlık kurtarma kodu; iki adımlı giriş (5 dk, 5 deneme); sır AES-256-GCM ile şifreli; aynı kod ikinci kez kabul edilmez |
| Yeniden doğrulama | Hassas işlemlerden önce parola + MFA; 5 dakika geçerli (`reauth_window_s`) |
| RBAC | 7 rol (SUPER_ADMIN, ADMIN, SUPPORT, ANALYST, FINANCE_MANAGER, OPERATIONS_MANAGER, CONTENT_MANAGER), 35 izin, 12 hassas izin; kontrol backend'de (`require_permission`) |
| Yönetici oturumu | Ayrı çerez (`mi_admin`, yalnızca `/admin/` yolu), ayrı köken listesi, en fazla 12 saat (varsayılan 8); MFA'sız personel giremez, personel MFA'yı kapatamaz |
| Denetim kaydı | Yalnızca ekleme; SHA-256 hash zinciri tetikleyicide; tetikleyici kapatılıp kayıt değiştirilse bile `audit_log_verify()` yakalar. Başarısız giriş/MFA denemeleri de kalıcı |
| Loglama | JSON loglar, istek kimliği (`X-Request-ID`), erişim logu, anahtar adı ve değer biçimine göre gizli bilgi maskeleme |
| İstek koruması | Köken (CSRF) denetimi, 256 KiB gövde sınırı, JSON derinlik sınırı, geçersiz UTF-8 reddi, güvenlik başlıkları |
| Hız sınırı | Redis kayan pencere (Lua ile atomik, tüm örnekler arasında paylaşılır); Redis düşerse süreç içi sınıra düşer |
| İşletim | `mi-admin migrate`, `mi-admin bootstrap` (**varsayılan parola yok**: tek kullanımlık parola belirleme bağlantısı), `mi-admin audit-verify`; `/health`, `/ready` (DB + şema sürümü + Redis) |
| Dağıtım | Dockerfile (çok aşamalı, root olmayan kullanıcı), `docker-compose.yml` (PostgreSQL + Redis + geçiş + API), GitHub Actions CI |

## 2. Dosyalar

```
.github/workflows/ci.yml          CI: lint, format, mypy (strict), pytest (PG16 + Redis7), imaj derlemesi, pip-audit
docker-compose.yml, .env.example  Yerel geliştirme yığını
api/pyproject.toml, uv.lock       Bağımlılıklar (kilitli)
api/alembic.ini, migrations/      Alembic; 0001_foundation.py + 0001_foundation.schema.sql
api/Dockerfile
api/src/mi_api/
  app.py          Uygulama fabrikası, /health, /ready
  config.py       Ayarlar + staging/production doğrulaması
  context.py      Oturum, yetki, istemci IP, hız sınırı bağımlılıkları
  db.py           Async motor ve oturumlar
  models.py       ORM modelleri
  rbac.py         Rol/izin kataloğu
  security.py     Argon2id, belirteç özeti, TOTP, kurtarma kodu, SecretBox
  audit.py        Denetim kaydı yazımı ve doğrulama
  logs.py         JSON log, maskeleme, istek kimliği
  guards.py       CSRF/gövde koruması
  ratelimit.py    Redis + bellek hız sınırı
  errors.py       Hata biçimi
  migrate.py      Alembic yardımcıları
  auth/router.py  /v1/auth uç noktaları
  auth/mfa.py     MFA doğrulama
  admin/router.py /admin/v1 uç noktaları
  cli.py, server.py
api/tests/        86 test
```

## 3. Veritabanı tabloları

| Tablo | Amaç | Öne çıkan güvence |
|---|---|---|
| `users` | Hesaplar | Parola yalnızca `$argon2id$`; e-posta küçük harf; MFA açıksa sır zorunlu; silinmiş ↔ `deleted_at` tutarlı |
| `user_sessions` | Uygulama ve yönetici oturumları | Belirteç yalnızca 32 baytlık SHA-256 özeti; `scope` ∈ {app, admin}; `state` ∈ {mfa_pending, active} |
| `email_tokens` | Doğrulama / sıfırlama | Yalnızca özet; tek kullanım; süreli; yenisi eskisini geçersiz kılar |
| `mfa_recovery_codes` | Kurtarma kodları | Yalnızca özet; tek kullanım |
| `roles`, `permissions`, `role_permissions` | RBAC kataloğu | Kod biçimi CHECK; test, kataloğun koddakiyle aynı olduğunu doğrular |
| `user_roles` | Rol atamaları | Son aktif SUPER_ADMIN silinemez (tetikleyici) |
| `audit_log` | Denetim kaydı | Hash zinciri; UPDATE/DELETE/TRUNCATE reddedilir |
| `email_outbox` | Giden e-posta kuyruğu | Hesap silinince bekleyen iletiler boşaltılır |
| `user_effective_permissions` (görünüm) | Kullanıcının etkin izinleri | — |

## 4. API uç noktaları

**Kullanıcı (`/v1/auth`)**: `POST register`, `POST verify-email`, `POST login`, `POST login/mfa`,
`POST logout`, `GET me`, `POST password/forgot`, `POST password/reset`, `POST password/change`,
`POST reauth`, `POST mfa/setup`, `POST mfa/enable`, `POST mfa/disable`, `GET sessions`,
`POST sessions/{id}/revoke`, `POST delete-account`.

**Yönetim (`/admin/v1`)**: `POST auth/login`, `POST auth/logout`, `POST auth/reauth`, `GET me`,
`GET users` (arama, durum/rol filtresi, sayfalama) — `users.read`, `GET users/{id}` (roller,
oturumlar, son 50 etkinlik) — `users.read`, `POST users/{id}/suspend` — `users.manage` + yeniden
doğrulama, `POST users/{id}/activate` — `users.manage` + yeniden doğrulama, `GET roles` — `roles.read`,
`PUT users/{id}/roles` — `roles.assign` + yeniden doğrulama, `GET audit` — `audit.read`,
`GET audit/verify` — `audit.read`.

**Sistem**: `GET /health`, `GET /ready`. Geliştirme ortamında `GET /docs` (üretimde kapalı).

## 5. Test sonuçları

Ortam: Python 3.13, gerçek PostgreSQL 16 ve Redis 7. Her test şablondan kopyalanan temiz bir
veritabanında çalışır.

| Dosya | Test | Kapsam |
|---|---|---|
| `test_auth.py` | 25 | Kayıt/doğrulama/giriş/çıkış, e-posta açığa vurmama, zayıf parola, başarısız girişin kalıcı denetimi, hız sınırı (11. denemede 429), askıya alınmış hesap, parola sıfırlama (tüm oturumlar kapanır, tek kullanım, süre, yeni belirteç eskisini iptal eder), parola değiştirme, oturum süresi, MFA iki adımlı giriş, kod tekrar reddi, kurtarma kodu tek kullanım, 5 denemede kilit, bekleyen oturum süresi, MFA kapatma, KEK yoksa 503, oturum listesi/kapatma, başkasının oturumu kapatılamaz, hesap silme anonimleştirir, CSRF |
| `test_admin.py` | 25 | Personel olmayan giremez, MFA'sız personel kayda yönlendirilir, hatalı kod, rol başına 10 izin senaryosu, hassas işlemde yeniden doğrulama, askıya alma oturumları kapatır, kendini/SUPER_ADMIN'i askıya alma engeli, son SUPER_ADMIN koruması, rol atama (MFA şartı, oturum kapatma, denetim ayrıntısı), ADMIN rol atayamaz, kendi rolünü değiştirememe, kullanıcı arama/filtre/sayfalama ve LIKE kaçışı, rol matrisi, denetim listesi/doğrulama, yönetici oturum süresi, yönetici kökeni |
| `test_schema.py` | 10 | Geçiş sürümü, ORM ↔ şema uyumu, RBAC kataloğu ↔ veritabanı, Argon2id/küçük harf/MFA CHECK'leri, son SUPER_ADMIN tetikleyicisi, denetim kaydı değiştirilemezliği ve zinciri, tetikleyici kapatılarak yapılan değişikliğin tespiti |
| `test_security_units.py` | 13 | RFC 6238 test vektörleri, TOTP penceresi ve tekrar, kurtarma kodu normalizasyonu, SecretBox AAD bağlama, Argon2id, maskeleme, JSON log maskeleme, JSON derinliği, production ayar doğrulaması |
| `test_app.py` | 8 | Health, istek kimliği, ready (sağlam / bekleyen geçiş / DB kapalı), gövde sınırları, hata biçimi |
| `test_ratelimit.py` | 3 | Bellek içi pencere, Redis'in örnekler arasında paylaşımı, Redis kapalıyken geri düşme |
| `test_cli.py` | 2 | İlk SUPER_ADMIN parolasız kurulur, ikinci kurulum reddedilir, bağlantı tek kullanımlık, kurulumdan yönetici girişine tam akış |

**Sonuç: 86/86 geçti.** `ruff check`, `ruff format --check`, `mypy --strict`: hatasız.
`pip-audit`: bilinen açık yok.

Ek elle doğrulama: gerçek `uvicorn` sunucusu başlatıldı; `/ready` → database/schema/redis `ok`;
yabancı kökenden giriş isteği 403; JSON erişim logları istek kimliğiyle yazıldı;
`mi-admin bootstrap` ilk yöneticiyi oluşturdu, ikinci çağrıyı reddetti; `mi-admin audit-verify` →
zincir sağlam.

## 6. Doğrulanamayanlar / eksik bağlantılar

| Konu | Durum |
|---|---|
| Docker imajı derlemesi | Bu ortamda Docker daemon'ı yok; `docker compose config` doğrulandı, imaj derlemesi CI'da (`docker` işi) |
| E-posta gönderimi | İletiler `email_outbox` tablosuna yazılıyor; gönderen işçi ve sağlayıcı M-G6 ile (Faz 6/9) |
| İkinci yönetici onayı (dört göz) | Faz 9'da (Admin Action Center); Faz 1'de hassas işlemler MFA + yeniden doğrulama + denetim kaydı ile korunuyor |
| Abonelik seviyesi (FREE/PRO/ELITE) | Faz 6 |
| Arayüz | Faz 7-8; bu fazda yalnızca API |

## 7. Güvenlik notları

* Üretimde (`staging`/`production`) uygulama şunlar olmadan **başlamaz**: HTTPS kökenler, Secure
  çerez, `MI_SECRET_KEK`, `MI_REDIS_URL`, `sslmode=verify-full`.
* Varsayılan yönetici parolası yoktur.
* Kullanıcı parolası ve özeti hiçbir API yanıtında yer almaz (testlerle doğrulandı).
* Açık konu: hesap silmede denetim kaydındaki IP adresleri saklama süresi boyunca kalır (denetim
  zinciri değiştirilemez). KVKK saklama süresi ve aydınlatma metni **hukukçu incelemesi** gerektirir
  (M-G4).

## 8. Sonraki aşama — Faz 2: Futbol verileri

Başlamak için **M-G1** kararı gerekiyor: veri sağlayıcısı (Sportmonks / API-Football /
football-data.org) ve API anahtarı. Anahtar gelene kadar uyarlayıcı arayüzü, şema ve kayıtlı örnek
yanıtlarla testler hazırlanabilir; arayüzde **gerçek veri geliyormuş gibi gösterilmez**.
