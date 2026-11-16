# Match Intelligence AI — 00. Teknik Denetim Raporu

> Tarih: 2026-11-16 · Kapsam: trading ürününü içeren `g2w4ypjjrp-lang/Can` deposunun tamamı · Amaç: Match Intelligence AI
> (futbol istihbarat ve analitik SaaS) geliştirmesine başlamadan önce mevcut durumu tespit etmek.

## 1. Özet

İncelenen `Can` deposu **boş değil** ve **futbolla ilgisi yok**. İçinde 17 aşaması tamamlanmış ayrı bir ticari ürün
var: **AI Trading Intelligence** (Binance kripto işlem motoru + bulut servisi + web sitesi/yönetim
paneli + Windows masaüstü + iOS). Bu ürün çalışır durumda, testleri ve CI'ı var.

**Karar:** Match Intelligence AI, trading ürünüyle **hiçbir dosyayı paylaşmayan ayrı bir proje**
olarak kurulur. Trading ürününün hiçbir dosyası değiştirilmez.

* Proje kendi deposunda geliştirilir: [`g2w4ypjjrp-lang/-dda`](https://github.com/g2w4ypjjrp-lang/-dda).
  Trading ürünü `g2w4ypjjrp-lang/Can` deposunda olduğu gibi kalır; iki depo arasında kod veya
  çalışma zamanı bağımlılığı yoktur.
* Gerekçe: iki ürünün alan modeli tamamen farklı (lisans kirası/cihaz/emir ↔ maç/tahmin/kupon/abonelik);
  aynı veritabanı veya API süreci iki ürünü birbirine kilitler, birinin geçişi/dağıtımı diğerini
  riske atar.
* Trading kodundaki **kanıtlanmış güvenlik yapı taşları** (Argon2id, oturum belirteci özeti, köken
  (CSRF) koruması, TOTP + kurtarma kodları, AES-GCM gizli değer kutusu, hash zincirli denetim kaydı;
  Faz 6'da PayTR/iyzico imza doğrulaması ve lisans anahtarı HMAC+pepper) Match'e **kopyalanarak**
  uyarlanır; iki proje arasında çalışma zamanı bağımlılığı yoktur.

## 2. Mevcut depo envanteri

| Bileşen | Klasör | Teknoloji | Durum (README ve kod incelemesine göre) |
|---|---|---|---|
| İşlem motoru | `engine/` | Python 3.12, asyncio, SQLite | Çalışır; Windows + Linux CI |
| Bulut servisi | `cloud/` | FastAPI, psycopg3 (ham SQL), PostgreSQL 16, 6 SQL geçişi | Çalışır; hesap, lisans, yönetici, ödeme (PayTR/iyzico/simülatör) |
| Web | `web/` | Next.js 16, React 19, Tailwind 4 | Çalışır; site, müşteri paneli, `/yonetim` admin paneli |
| Masaüstü | `desktop/` | Tauri 2, React | Çalışır (imzasız) |
| iOS | `ios/` | SwiftUI | Kod + test |
| Protokol | `shared/protocol/` | JSON Schema + test vektörleri | — |
| CI | `.github/workflows/` | ci, web, desktop, ios, security | Gizli bilgi taraması, `pip-audit`, `npm audit` |

Temel kalıp: her aşama "kod + test + belge" ile kapanıyor; dış onay gerektiren adımlar (canlı ödeme,
dağıtım, imzalama) "onay kapısı" (G1–G6) olarak bekletiliyor. Match aynı disiplini kullanır.

## 3. Match Intelligence AI açısından durum

| Alan | Mevcut durum | Match için anlamı |
|---|---|---|
| Futbol verisi | **Yok** | Sıfırdan: sağlayıcı uyarlayıcısı, şema, zamanlanmış güncelleme |
| Tahmin/AI motoru | Trading'e özgü modeller var, futbolla ilgisi yok | Sıfırdan: Poisson / Dixon-Coles / Elo / GBM, Optuna, kalibrasyon |
| Kupon / value / sanal simülasyon | Yok (trading'de "paper trading" kavramı var) | Sıfırdan, sanal bakiye defteri (ledger) mantığı trading'den esinlenir |
| Kimlik doğrulama | `cloud/accounts.py`: Argon2id, çerez oturumu, e-posta doğrulama, parola sıfırlama | Taşınır; SQLAlchemy'ye uyarlanır |
| Yönetici güvenliği | `cloud/admin/security.py`: TOTP, kurtarma kodları, AES-GCM kutusu | Taşınır; MFA müşteri hesaplarına da açılır |
| RBAC | Yönetici rolleri + izin görünümü (SQL) | İstenen 7 rol ve izin matrisine yeniden kurulur |
| Denetim kaydı | PostgreSQL tetikleyicisiyle hash zinciri, değiştirilemez | Aynı tasarım Alembic geçişine taşınır |
| İstek koruması | `cloud/guards.py`: köken (CSRF), gövde boyutu, JSON derinliği | Taşınır |
| Hız sınırı | Bellek içi kayan pencere ("çok örnekte Redis" notu var) | Redis tabanlı yapıldı (bellek içi yedekli) |
| Ödeme | PayTR, iyzico uyarlayıcıları + imza doğrulama + idempotent teslim | Faz 6'da abonelik modeline uyarlanarak taşınır |
| Lisans | HMAC+pepper ile arama özeti, AES zarf şifreleme | Faz 6'da taşınır |
| Tasarım sistemi | Trading markası, tek tema | Kullanılmaz; Match için 10 tasarım sistemi sıfırdan |
| Celery / Redis kuyruğu | Yok | Faz 2'de eklenir |
| SQLAlchemy / Alembic | Yok (ham SQL + kendi geçiş çalıştırıcısı) | Match'te istenen yığın kullanılır (aşağıda gerekçe) |

### Neden Match'te ham SQL yerine SQLAlchemy + Alembic?

Mevcut `cloud/` ham SQL ile çok iyi çalışıyor; değiştirilmiyor. Match'te ise veri modeli çok daha
geniş (ülke, lig, sezon, takım, oyuncu, maç, istatistik, tahmin, kupon, abonelik, tasarım sürümleri
... 60+ tablo öngörülüyor) ve Data Explorer / admin modülleri genel sorgu üretimi istiyor. ORM modelleri
hem bu genel ekranları hem de tip güvenli sorguları kolaylaştırır. Veritabanı düzeyindeki güvenceler
(denetim zinciri tetikleyicisi, CHECK kısıtları, değiştirilemez tahmin kayıtları) Alembic geçişlerinde
ham SQL olarak korunur — ORM bunların yerine geçmez.

## 4. Tespit edilen sorunlar ve riskler

| # | Bulgu | Önem | Öneri |
|---|---|---|---|
| R1 | İstenen ürün kapsamı (10 tasarım sistemi × 11 ekran, 30 admin modülü, çok modelli AI, ödeme) birkaç aylık ekip işidir; tek seferde yazılırsa yüzeysel olur | Yüksek | Fazlara bölünmüş geliştirme, her fazda test ve rapor ([01-yol-haritasi](01-yol-haritasi.md)) |
| R2 | Gerçek futbol verisi için **lisanslı sağlayıcı ve API anahtarı yok** | Engelleyici (Faz 2) | Onay kapısı **M-G1**: sağlayıcı seçimi ve anahtar |
| R3 | Gerçek oran verisi lisansı yok; EV/CLV hesaplanamaz | Faz 4'te engelleyici | Onay kapısı **M-G2**: oran verisi; o güne kadar EV gösterilmez |
| R4 | Bahis/tahmin içeriği Türkiye'de düzenlemeye tabi (7258 sayılı Kanun, reklam kısıtları); ürün "analiz + sanal simülasyon" olarak konumlanmalı | Yüksek (hukuki) | Hukuk incelemesi (M-G4); ürün hiçbir zaman gerçek bahis işlemi yapmaz |
| R5 | Trading ürünü ve Match aynı alan adını (`canarslan.net.tr`) paylaşırsa çerez/oturum karışabilir | Orta | Match ayrı alan adı veya alt alan adı (M-G3 dağıtım kararı) |
| R6 | Trading bulut hız sınırı bellek içi; birden çok örnekte etkisiz | Orta (trading) | Trading'e dokunulmadı; Match'te Redis ile çözüldü |
| R7 | Geliştirme ortamında Docker daemon'ı yok; imaj derlemesi burada doğrulanamadı | Düşük | CI'da `docker build` + `docker compose config` işi |

Trading ürününde yeni bir güvenlik açığı bulunmadı (bu denetim Match'e odaklıdır; trading'in kendi
Aşama 18 sızma testleri depoda mevcut).

## 5. Temel ölçümler

* Trading bulut servisi test paketi (dokunulmadan) bu ortamda gerçek PostgreSQL 16 ile
  çalıştırıldı: **160 test geçti**, 0 başarısız.
* Ortam: Python 3.13, Node 22, PostgreSQL 16, Redis 7 yerel olarak mevcut.
