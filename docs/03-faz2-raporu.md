# Faz 2 Raporu — Futbol Veri Altyapısı

> Durum: **Altyapı tamamlandı (kod + otomatik testler).** Gerçek veri akışı **M-G1** (sağlayıcı
> aboneliği ve API anahtarı) ile başlar. Anahtar olmadan sistem veri uydurmaz; işler "atlandı"
> olarak kaydedilir ve API `data_status: "no_provider"` döner.

## 1. Tamamlanan işler

| Alan | Uygulama |
|---|---|
| Provider Adapter | Sağlayıcıdan bağımsız veri biçimi (`football/providers/base.py`) + iki uyarlayıcı: **API-Football v3** (fikstür, canlı, puan durumu, takım istatistiği, xG, kadro, sakatlık/ceza) ve **football-data.org v4** (fikstür, canlı, puan durumu). Desteklenmeyen veri türü açıkça `CapabilityNotSupported` döner |
| Veritabanı | Geçiş `0002`: 14 tablo — ülke, lig, sezon, stat, takım, oyuncu, maç, takım maç istatistiği, puan durumu, kadro, kadro oyuncuları, eksik oyuncular, sağlayıcı durumu, senkronizasyon kayıtları |
| Kaynak ve tazelik | Her kayıtta `provider`, `external_id`, `fetched_at` (varsa `source_updated_at`). Gecikmeli gelen eski yanıt yeni veriyi ezemez |
| Skor ayrımı | İlk yarı, normal süre (90'), uzatma devresi, penaltı atışları ayrı alanlarda. Modeller 90' skorunu kullanır; penaltılar skora katılmaz |
| Zaman | Veritabanında UTC; API Türkiye saatini de verir. `date` filtresi Türkiye takvim günüdür (16 Kasım 22:30 UTC maçı 17 Kasım'da listelenir) |
| Kota yönetimi | Yerel günlük + dakikalık bütçe (Redis'te, tüm işçiler arasında ortak) ve sağlayıcının yanıt başlıklarında bildirdiği kalan hak. Düşük öncelikli işler (kadro, istatistik, puan durumu, geçmiş veri) günlük bütçenin rezerv payına (varsayılan %20) giremez; o pay canlı maç ve günün fikstürüne kalır |
| Senkronizasyon işleri | `fixtures_date`, `live` (canlı/başlamak üzere maç yoksa hiç istek atmaz), `fixture_details`, `upcoming_details`, `standings`, `standings_active`, `season_backfill` (sayfalı tarihsel veri). Her çalışma `football_sync_runs`'a yazılır: durum, istek sayısı, kayıt sayısı, mesaj |
| Zamanlayıcı | Celery işçisi + Celery Beat: bugün 10 dk, dün/yarın 1 saat, canlı 60 sn, maç öncesi/sonrası ayrıntı 15 dk, puan durumu 6 saat. Aynı iş aynı anda iki kez çalışmaz (Redis kilidi) |
| Takip edilen ligler | Fikstür tüm ligler için tek istekle gelir; kadro, istatistik, puan durumu gibi ek istekler yalnızca yönetim panelinden "takip edilen" yapılan liglere atılır (kota tasarrufu) |
| Veri kalitesi | Tazelik kuralı (canlı 3 dk, 24 saat içindeki maç 1 saat, uzak maç 24 saat; bitmiş maç bayatlamaz) ve 0–100 **veri tamlığı puanı** (tahmin kalitesi değil; eksik istatistik, xG, ilk 11, ilk yarı skoru ve bayatlık için düşer) |
| API | Herkese açık okuma uçları + yönetim uçları (yetki ve denetim kaydıyla) |
| İşletim | `mi-admin football-sync <iş>` (elle çalıştırma / tarihsel yükleme); `docker-compose`'a `worker` ve `beat` servisleri |

## 2. Yeni tablolar

`football_countries`, `football_competitions` (`is_active` = takip edilen lig),
`football_seasons`, `football_venues`, `football_teams`, `football_players`, `football_fixtures`,
`football_fixture_team_stats`, `football_standings`, `football_lineups`,
`football_lineup_players`, `football_absences`, `football_provider_status`, `football_sync_runs`.

Veritabanı kısıtları: geçerli maç durumu listesi, ev ≠ deplasman, bitmiş maçta skor zorunlu, negatif
gol/istatistik yok, topla oynama 0–100, puan durumunda G+B+M = O.

## 3. API uç noktaları

**Herkese açık** (abonelik kısıtları Faz 6'da):
* `GET /v1/football/status` — sağlayıcı, son başarılı senkronizasyon, `data_status`
* `GET /v1/football/fixtures?date=&competition_id=&status=` — Türkiye gününe göre maçlar; her maçta skor kırılımı, kaynak, tazelik
* `GET /v1/football/fixtures/{id}` — stat, hakem, takım istatistikleri (xG dahil), ilk 11/yedekler, eksik oyuncular, veri tamlığı puanı
* `GET /v1/football/competitions?active_only=&q=`
* `GET /v1/football/competitions/{id}/standings?season=`

**Yönetim:**
* `GET /admin/v1/football/status` — `football.read`: yetenekler, kota bütçesi ve bugünkü kullanım, sağlayıcının bildirdiği kalan hak, son hata, maç durum sayıları
* `GET /admin/v1/football/sync-runs?job=&status=` — `football.read`
* `POST /admin/v1/football/sync` — `football.manage`: işi hemen çalıştırır, sonucu döner, denetim kaydı yazar
* `PATCH /admin/v1/football/competitions/{id}` — `football.manage`: ligi takibe al / çıkar (denetim kaydı)

## 4. Test sonuçları

| Dosya | Test | Kapsam |
|---|---|---|
| `test_football_providers.py` | 10 | API-Football ayrıştırma (normal, penaltılı kupa maçı, stat yok), sayfalama, istatistik/xG/kadro/sakatlık/ceza ayrımı, puan durumu, hata zarfı (anahtar / kota), 5xx yeniden deneme, 401/429/500, kota kancasının isteği engellemesi, bilinmeyen durum ve saat dilimsiz zaman reddi, football-data.org maçlar (gün süzme, penaltı skoru), puan durumu (yalnızca TOTAL), desteklenmeyen veri türleri |
| `test_football_sync.py` | 14 | Sağlayıcı yokken veri üretmeme, idempotent yazma, eski yanıtın yeni veriyi ezememesi, canlı işin gereksiz istek atmaması, canlıdan düşen maçın son skorunun alınması, maç ayrıntıları ve listelerin yenilenmesi, geçersiz girdi, takip edilen lig kuralı, puan durumu, sayfalı tarihsel yükleme, öncelikli kota bütçesi, sağlayıcının bildirdiği kotaya uyma, hata kaydı, desteklenmeyen ayrıntılar |
| `test_football_api.py` | 10 | Sağlayıcı yok durumu, Türkiye günü gruplaması, varsayılan günün Türkiye saatine göre seçilmesi, filtreler, bayat verinin işaretlenmesi, maç detayı (istatistik, xG, kadro, eksikler, tamlık puanı), puan durumu, lig listesi, yönetim uçlarında rol bazlı yetki + denetim kaydı, tazelik kuralları |

**Toplam (Faz 1 + 2): 120/120 geçti** — gerçek PostgreSQL 16 ve Redis 7 üzerinde. `ruff`,
`ruff format`, `mypy --strict`: hatasız.

Ek elle doğrulama: geliştirme veritabanına `0002` uygulandı; `mi-admin football-sync` sağlayıcı
yokken "atlandı" kaydı yazdı; Celery işçisi Redis kuyruğundan görevi alıp çalıştırdı (JSON log).

**Test verisi hakkında:** sağlayıcı yanıt örnekleri (`api/tests/samples/`) belgelenmiş biçimi taklit
eden, **kurgusal takımlarla** elle yazılmış dosyalardır. Uygulamada gösterilmez, tohum verisi olarak
kullanılmaz.

## 5. Doğrulanamayanlar / eksik bağlantılar

| Konu | Durum |
|---|---|
| Gerçek sağlayıcı yanıtları | **M-G1** bekliyor. Uyarlayıcılar belgeye göre yazıldı; ilk gerçek anahtarla canlı doğrulama yapılacak ve fark çıkarsa düzeltilecek |
| Oyuncu bazlı maç performansı, teknik direktör geçmişi, oyuncu dakikaları | Şema genişletmesi Faz 3 öncesinde (özellik mühendisliği ihtiyacına göre); API-Football `/fixtures/players` ile |
| Birden fazla sağlayıcının aynı takımı eşleştirmesi | Şu an tek etkin sağlayıcı; çapraz eşleme tablosu gerekirse eklenecek |
| WebSocket ile canlı skor yayını | Faz 7 (arayüz) ile birlikte |
| Oran verisi | **M-G2** |
| Docker imajı | Bu ortamda Docker daemon'ı yok; CI'da derleniyor |

## 6. Güvenlik notları

* Sağlayıcı API anahtarı yalnızca sunucuda ortam değişkeni / gizli bilgi deposunda; API yanıtlarında,
  loglarda ve denetim kaydında yer almaz (log maskeleme).
* Sağlayıcı seçiliyken anahtar boşsa uygulama başlamaz.
* Yönetimden tetiklenen her senkronizasyon ve lig takibi değişikliği denetim kaydına yazılır.

## 7. Sıradaki adım

1. **M-G1:** Sağlayıcı seçimi ve API anahtarı → `MI_FOOTBALL_PROVIDER`, `MI_FOOTBALL_API_KEY`.
   Ardından: canlı doğrulama, takip edilecek liglerin seçimi, 2–3 sezonluk tarihsel veri yüklemesi
   (`mi-admin football-sync season_backfill --competition-id … --season …`).
2. **Faz 3 — AI:** tarihsel veri üzerinde zaman sıralı özellik deposu (sızıntı testiyle), Elo,
   Poisson, Dixon-Coles temel modelleri, kronolojik doğrulama, Brier / log loss / kalibrasyon.
   Gerçek veri gelmeden model metrikleri **raporlanmayacak**; altyapı sentetik veriyle yalnızca
   doğruluk (matematik) testlerinden geçirilecek.
