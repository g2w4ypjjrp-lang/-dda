# Faz 4 Raporu — Kupon Motoru

> Durum: **Kupon motoru, kayıt, sonuçlandırma ve Kupon Merkezi tamamlandı (kod + testler).**
> Oran/EV/CLV **M-G2** (lisanslı oran verisi) ile; ilk yarı piyasaları bir sonraki adımda.

## 1. Tamamlanan işler

| Alan | Uygulama |
|---|---|
| Ortak skor dağılımı | Her yeni tahmin kaydı, tam skor olasılık matrisini (0–10 gol) da saklar; yayımlanan 1X2 ile tutarlı (testle doğrulandı) |
| Piyasalar | Maç sonucu (1/X/2), çifte şans (1X/12/X2), alt/üst (1.5/2.5/3.5), karşılıklı gol (var/yok) — hepsi skor üzerinde tanımlı koşullar |
| Birleşik olasılık | **Aynı maçtaki seçimler çarpılmaz**: ortak skor dağılımında hepsinin birlikte gerçekleştiği skorların olasılığı toplanır (kesin). Farklı maçlar model koşulunda bağımsız kabul edilip çarpılır; bu varsayım her kuponda yazılır |
| Monte Carlo | Sabit tohumlu (42) 10.000 ve 50.000 simülasyon; her maçın skoru kendi dağılımından örneklenir, kupon bütün olarak değerlendirilir. Kesin değerle 4 standart hata içinde uyuşma "doğrulandı" olarak gösterilir |
| Otomatik kupon | Profil: düşük risk (seçim olasılığı ≥ %70), dengeli (%55–78), yüksek risk (%38–62); düşük/dengeli yalnızca orta+ güvenilirlik. Maç başına tek seçim, en olası (güvenilirlikle ağırlıklı) maçlar; gün, maç sayısı (1–10), lig ve piyasa filtresi. Yeterli maç yoksa nedenini söyler, kupon uydurmaz |
| Kayıt | Olasılıklar **sunucuda** tahmin kayıtlarından yeniden hesaplanır (istemciye güvenilmez). Yalnızca maçın **en güncel**, yayımlanmış tahmini kabul edilir; başlamış/başlamak üzere (5 dk) maç reddedilir |
| Değiştirilemezlik | Kupon ilk maçtan önce kaydedilmek zorunda (veritabanı kısıtı). İçerik değiştirilemez/silinemez; yalnızca sonuç "beklemede"den bir kez son duruma geçer (tetikleyici) |
| Sonuçlandırma | 90' skoruna göre seçim tutar/tutmaz; iptal/yarıda kalan maç "geçersiz". Bir seçim tutmazsa kupon kaybeder; kalanların hepsi tutar veya geçersizse kazanır. Celery Beat 15 dakikada bir + yönetimden elle |
| Oran | Oran verisi yok: toplam oran ve EV hesaplanmaz, alan `null` ve açıklama metni döner |
| Denetim | Kupon oluşturma ve yönetici sonuçlandırması denetim kaydına yazılır |

## 2. Yeni tablolar (geçiş 0004)

`coupons`, `coupon_legs` — değiştirilemez içerik, tek seferlik sonuç.

## 3. API

* `POST /v1/coupons/generate` — otomatik kupon taslağı (oturum gerekli, kullanıcı başına 10 dk'da 30)
* `POST /v1/coupons` — kaydet; `GET /v1/coupons`, `GET /v1/coupons/{id}` — yalnızca kendi kuponları
* `GET /admin/v1/coupons` — `coupons.read`: durum sayıları, sonuçlananlarda **beklenen ortalama olasılık ile gerçekleşen oran**
* `POST /admin/v1/coupons/settle` — `coupons.manage`

## 4. Arayüz

* **Kupon Merkezi** (`/kuponlar`, menüde): gün, risk profili, maç sayısı, piyasa filtresi → önerilen
  kupon (seçimler, model güvenilirliği, birleşik olasılık, "≈ her N kupondan 1", simülasyon doğrulaması,
  bağımsızlık varsayımı, risk açıklaması, oran yok notu, uyarı) → kaydet → değiştirilemez geçmiş
  (tuttu/tutmadı/geçersiz/bekliyor, maç skorları).
* Yönetim Command Center'da kupon özeti (beklenen vs gerçekleşen).

## 5. Test sonuçları

| Paket | Test | Kapsam |
|---|---|---|
| api `test_coupon_engine.py` | 7 | Aynı maç ortak olasılığı (elle toplamla eşit, saf çarpımdan farklı), çelişen seçimler = 0, piyasa bölünmeleri/tümleyenleri, maçlar arası çarpım + Monte Carlo uyumu ve tekrar üretilebilirlik, matrissiz eski kayıtta tek seçim / çoklu seçim reddi, profil bantları ve güvenilirlik, risk metni |
| api `test_coupons_api.py` | 6 | Giriş zorunluluğu, taslak üretimi ve yetersiz aday, sunucu tarafı yeniden hesap + aynı maç ortak olasılığı, içerik değiştirilemezliği (UPDATE/DELETE reddi), kopya seçim, eski tahmin ve başlamış maç reddi, başkasının kuponuna erişememe, sonuçlandırma (tuttu/tutmadı/geçersiz, tek seferlik), yönetim yetkileri ve özet, denetim kaydı, maçtan sonra kupon yazılamaması |
| ml `test_pipeline_db.py` | (güncellendi) | Tahmin kaydında skor matrisi: toplam 1, 1X2 ile tutarlı |
| web E2E `coupons.spec.ts` | 1 | Girişsiz uyarı → kayıt/giriş → kupon oluştur → simülasyon doğrulaması ve oran notu → kaydet → geçmişte "Bekliyor" |

**Toplam: API 138/138, ML 32/32, web E2E 7/7** (gerçek PostgreSQL 16 + Redis 7). `ruff`,
`mypy --strict`, `tsc` strict: temiz.

## 6. Eksikler

| Konu | Durum |
|---|---|
| Oran, EV, CLV, açılış/kapanış oranı | **M-G2** |
| İlk yarı piyasaları (İY 1X2, İY alt/üst) | İlk yarı skor modeli gerekiyor — sıradaki iş |
| Maçlar arası bağımlılık (aynı gün, aynı lig) | Şu an model koşulunda bağımsız; gerçek veride kalıntı korelasyon ölçülüp gerekirse eklenecek |
| Maç sayfasından "kupona ekle" ve elle çoklu seçim arayüzü | API hazır (`POST /v1/coupons` elle seçim alır); arayüz sonraki adım |
| Plan bazlı sınırlar (FREE/PRO) | Faz 6 |
| Sanal bakiye ile kupon simülasyonu | Faz 5 |
