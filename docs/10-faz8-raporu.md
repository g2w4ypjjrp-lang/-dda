# Faz 8 Raporu — On Tasarım Sistemi ve Design Studio

> Durum: **Tamamlandı (kod + testler).** On tasarımın her biri gerçek uygulama bileşenleriyle
> çalışır; önizlemeler canlı sayfalardır. Tasarımlar yalnızca renk teması değildir: kabuk
> (gezinme yapısı), ana sayfa kompozisyonu, maç listesi düzeni, kart geometrisi, tipografi,
> yoğunluk, tablo/grafik/düğme stili, hareket ve mobil gezinme ayrı seçilir.

## 1. Mimari

* **Yapılandırma = sürümlü JSON** (`design_versions`). Katı şema (`api/src/mi_api/design/schema.py`):
  yalnızca `#rrggbb(aa)` renk, aralıklı sayı ve izinli seçenek kabul edilir; web tarafı da her
  değeri yeniden denetler. Yapılandırma sayfa CSS'ine yazıldığı için bu, **CSS enjeksiyonunu**
  engeller (testte `"red;} body{...}"`, `url(...)`, sahte font adı reddedilir).
* **Sunucu tarafı işleme:** kök yerleşim `GET /v1/design`'ı okur, yayımlanmış on tasarımı
  `[data-design="..."]` CSS değişkenlerine çevirir, kullanıcının seçimini (çerez) veya site
  varsayılanını `<html>` özniteliklerine (`data-shell`, `data-card`, `data-density`, `data-menu`,
  `data-button`, `data-table`, `data-chart`, `data-motion`, `data-mobile-nav`) yazar. Sayfa ilk
  yüklemede doğru tasarımla gelir. API'ye ulaşılamazsa Signature Black ile devam eder.
* **Yoğunluk** Tailwind'in aralık ölçeğini (`--spacing`) değiştirir: tüm boşluklar tutarlı ölçeklenir.
* **Fontlar** yerel paketlerden (fontsource; Türkçe karakter alt kümeleri, yalnızca kullanılınca
  yüklenir). Dış font sunucusuna istek yok. CSP değişmedi (`font-src 'self'`).

## 2. On tasarım

| # | Tasarım | Kabuk | Ana sayfa | Maç listesi | Kart | Tipografi | Mod |
|---|---|---|---|---|---|---|---|
| 01 | Signature Black (varsayılan) | Üst çubuk | Katmanlı başlık + günün özeti | Satır | Yükseltilmiş | Inter | Koyu |
| 02 | Swiss Intelligence | Üst çubuk (alt çizgi menü) | Tipografik ifade + numaralı dizin | Tablo | Çizgili, 2 px köşe | Inter | Açık |
| 03 | Quantum Terminal | Terminal + gerçek veri durum şeridi | Panolar (günün tahtası, model, sistem) | Tablo (zebra) | Çizgili, 3 px | IBM Plex + Plex Mono, kompakt | Koyu |
| 04 | Editorial Sports | Gazete başlığı (masthead) | Günün maçı kapağı + manşet listesi | Kart | Düz | Fraunces + DM Sans | Açık |
| 05 | AI Atelier | Kenar çubuğu | Olasılık dağılımı + belirsizlik aralığı | Satır | Çizgili | Space Grotesk + Inter | Koyu |
| 06 | Architectural Luxury | Geniş kenar çubuğu | Asimetrik blok ızgarası | Kart | Çentikli geometri | Manrope 300 | Açık |
| 07 | Institutional Blue | Üst çubuk | Günlük analiz raporu + KPI + tablo | Tablo (zebra) | Çizgili | IBM Plex, kompakt | Açık |
| 08 | Obsidian Glass | Üst çubuk | Üst üste binen cam paneller | Kart | Cam (kontrollü bulanıklık) | Manrope | Koyu |
| 09 | Future Sports Lab | Üst çubuk (blok menü) | Takım karşılaştırması | Kart | Yükseltilmiş | Space Grotesk 700 | Koyu |
| 10 | Match Intelligence Signature | Gazete başlığı | Marka işareti + günün olasılık şeritleri | Satır | Yükseltilmiş, 20 px | Space Grotesk + DM Sans | Açık |

* Her tasarımın kendi **logo** varyantı var (monogram, kelime işareti, terminal, serif, DESIGN 10'a
  özel "orta yuvarlak + 1·X·2 şeridi" işareti).
* Mobil gezinme: alt sekmeler, açılır menü veya üstte kayan sekmeler (tasarıma göre).
* Tüm ana sayfa kompozisyonları **gerçek veriden** beslenir (bugünün maçları, yayımlanmış
  tahminler, ölçülmüş performans). Veri yoksa "veri yok" yazar; örnek rakam yoktur. Terminal durum
  şeridi de gerçek sayılardır (maç, canlı, yayımlanan AI analizi, kaynak).
* Kullanıcı **Panelim → Görünüm**'den tasarım seçebilir (çerezde saklanır) veya site varsayılanına dönebilir.

## 3. Design Studio (`/yonetim/tasarim`)

| Özellik | Uygulama |
|---|---|
| Galeri | On tasarım; gerçek tokenlarla çizilen önizleme kutusu, yayındaki sürüm, açık taslak, varsayılan rozeti |
| Tam ekran önizleme | Gerçek sayfa iframe içinde: ana sayfa, dashboard, maç merkezi, maç detayı, AI analizi, kupon merkezi, abonelik, admin paneli |
| Cihaz | Masaüstü (1440), tablet (834), mobil (390): gerçek genişlikte işlenip kutuya ölçeklenir |
| Karşılaştırma | İki tasarım yan yana, aynı sayfa ve cihazda |
| Düzenleyici | 19 renk, metin/başlık/mono font, font boyutu ve ölçek, başlık ağırlığı ve harf aralığı, kart geometrisi, köşe yarıçapı, kenarlık, gölge, kabuk/menü, kenar çubuğu ve sayfa genişliği, ızgara aralığı ve sütun (12/16), veri yoğunluğu, ana sayfa kompozisyonu, maç listesi, logo, düğme/tablo/grafik stili, grafik çizgi kalınlığı ve ızgara, animasyon düzeyi ve süresi, mobil navigasyon |
| Canlı önizleme | Kaydetmeden her değişiklik önizleme çerçevesine aynı köken mesajıyla iletilir |
| Yayınlama | Taslağı kaydet → önizle → **yayınla** (onay penceresi + hassas izin, son 5 dk'da yeniden doğrulama) |
| Sürüm geçmişi | Tüm sürümler (yayında/arşiv/taslak/atıldı), herhangi bir sürümü önizleme |
| Geri alma | Eski sürümün yapılandırması **yeni sürüm** olarak yayımlanır; geçmiş silinmez |
| Varsayılan | Site varsayılan tasarımı (onaylı) |

İzinler: `design.read` görüntüleme, `design.edit` taslak (CONTENT_MANAGER), `design.publish`
yayın/geri alma/varsayılan (ADMIN, SUPER_ADMIN). Tüm işlemler denetim kaydında. Yayımlanmış
sürüm veritabanı tetikleyicisiyle değiştirilemez ve silinemez.

## 4. Yeni / değişen

* API: `mi_api/design/` (şema, varsayılanlar, modeller, API), geçiş `0008_design`
  (`design_versions`, `design_settings`, tasarım başına tek yayımlanmış ve tek açık taslak).
* Web: `lib/design.ts` (CSS üretimi + doğrulama), `components/design.tsx` (sağlayıcı, önizleme,
  seçim), `components/SiteHeader.tsx` (dört kabuk + üç mobil gezinme), `components/heroes.tsx`
  (on kompozisyon), `components/match.tsx` (satır/kart/tablo), `components/Logo.tsx` (beş logo),
  `components/DesignSwatch.tsx`, `app/yonetim/(panel)/tasarim`, sanal portföy grafiği tasarımın
  grafik stilini kullanır.
* Güvenlik başlığı: önizleme iframe'i için `frame-ancestors 'self'` ve `X-Frame-Options:
  SAMEORIGIN` (başka sitelerin çerçevelemesi hâlâ engelli).
* Düzeltme: panelden "Çıkış" sonrası kullanıcı ana sayfa yerine giriş sayfasına düşebiliyordu
  (yönlendirme yarışı); giderildi. Ana sayfa üyelik kartları artık Paketler sayfasına bağlanıyor.

## 5. Testler

| Dosya | Test | Kapsam |
|---|---|---|
| api `test_design.py` | 10 | On varsayılan şemadan geçer ve yerleşimleri farklıdır (10 farklı ana sayfa, 4 kabuk, 3 liste, 5 kart); 6 CSS enjeksiyonu/aralık dışı deneme reddi; herkese açık uç; taslak → düzenle → geçersiz yapılandırma reddi → içerik yöneticisi yayımlayamaz → yayın (onaysız reddedilir) → yayımlanan sürüm API ve veritabanında değiştirilemez/silinemez → geri alma v3 → taslak atma → varsayılan; denetim kaydı sırası; yeniden doğrulama zorunluluğu; SUPPORT erişemez |
| web E2E `design.spec.ts` | 2 | Kullanıcı Quantum Terminal seçer → terminal kabuğu ve gerçek veri şeridi; Editorial → masthead; site varsayılanına dönüş. Yönetici: Studio galeri (10), iframe önizleme, taslak → vurgu rengi ve ana sayfa düzeni değişikliği → kaydet → onaylı yayın → herkese açık uçta v2 → geçmişten v1'e dönüş (v3) |

**Toplam: API 174/174, ML 37/37, web E2E 12/12** (gerçek PostgreSQL 16 + Redis 7). `ruff`,
`mypy --strict`, `tsc` strict, `next build`: temiz.

Not: kayıt uç noktası IP başına saatte 10 kayıtla sınırlı. Aynı Redis ile E2E'yi art arda
koşturunca 429 alınabilir. `e2e/reset-local.sh` artık hız sınırı sayaçlarını da temizliyor.

## 6. Sınırlar ve eksikler

| Konu | Durum |
|---|---|
| Sayfa başına tamamen ayrı el yapımı yerleşim (110 ekran) | Yapılmadı. Tasarımlar ortak bileşenler üzerinde kabuk, ana sayfa kompozisyonu, maç listesi ve CSS varyantlarıyla ayrışıyor. Maç detayı, kupon, panel ve paketler sayfaları tasarımın kabuğunu, tipografisini, kartlarını ve yoğunluğunu alıyor ama aynı bilgi düzenini kullanıyor. |
| Admin paneli düzeni | Admin tokenları alır (renk, font, kart); gezinme düzeni tasarıma göre değişmez |
| Görsel regresyon testi (ekran görüntüsü karşılaştırma) | Faz 10 |
| Kullanıcı tasarım tercihinin hesaba bağlanması (cihazlar arası) | Şimdilik tarayıcı çerezi |
| Erişilebilirlik kontrast denetimi (otomatik) | Düzenleyicide renk kontrastı uyarısı Faz 10'da |
