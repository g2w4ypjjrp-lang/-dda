# Faz 7 Raporu (kalanlar) — Kişisel Panel, Favoriler, Bildirimler, İçerik, PWA

> Durum: **Tamamlandı (kod + testler).** E-posta ve push gönderimi sağlayıcı onayı (M-G6) bekliyor.
> E-postalar şimdiden gerçek bir kuyruğa yazılıyor ama gönderilmiş gibi gösterilmiyor. Yasal metinler
> hukuk onayı (M-G4) olmadan yayımlanmıyor; sitede "hukuki inceleme sürecinde" yazıyor.

## 1. Kişiselleştirilebilir panel

* **11 bileşen (widget):** hesap özeti, abonelik durumu, günün maçları, öne çıkan analizler, favori
  takımlar, favori ligler, kaydedilmiş maçlar, kupon geçmişi, sanal bakiye ve simülasyon,
  bildirimler, son aktiviteler. Her biri gerçek veriden beslenir; veri yoksa "yok" der (ör.
  "Sanal portföy açılmadı", "Kupon oluşturucu PRO paketinde").
* **Düzenleme modu:** bileşen ekleme/kaldırma, yukarı/aşağı taşıma, boyut (küçük/orta/geniş = 4/6/12
  sütun), **sunucuda kaydetme** (`/v1/dashboard/layout`, kişiye özel), varsayılana dönme. Sunucu
  bilinmeyen veya yinelenen bileşeni reddeder.
* Hesap ve güvenlik kartları (paket ve lisans, MFA, görünüm, oturumlar, hesap silme) panelin
  altında "Hesap ve güvenlik" bölümünde.

## 2. Favoriler ve kaydedilmiş maçlar

* Maç sayfasında her takımın yanında yıldız ve "Maçı kaydet". Lig sayfasında "Favorilere ekle".
* `/v1/favorites/fixtures`: favori takım ve liglerin dün ile önümüzdeki 7 gün arasındaki maçları,
  kaydedilmiş maçlar. Panel bileşenleri bunu kullanır.

## 3. Bildirim sistemi

| Kategori | Ne zaman | Kaynak |
|---|---|---|
| Güvenlik | Son 90 günde görülmemiş IP'den giriş (ilk giriş hariç), parola değişikliği/sıfırlama, MFA açma/kapama | İstek anında |
| Abonelik | Paket etkinleşti (ödeme, lisans, yönetici), sipariş iade edildi, paket 3 gün içinde bitiyor | İstek anında + tarama |
| Kupon | Kupon sonuçlandı (tuttu / tutmadı / geçersiz) | Sonuçlandırma işi |
| Maç | Favori takımın veya kaydedilmiş maçın başlamasına ≤60 dk | Tarama (5 dk) |
| Sonuç | Favori maç bitti (90' skoru) | Tarama (5 dk) |
| Sistem | Yönetici duyurusu | İçerik & Duyurular |

* **Tekrarsız:** her olay `dedupe_key` ile kullanıcı başına bir kez (veritabanı benzersiz indeksi).
  Tarama işi tekrar çalışsa da çoğaltmaz (testli).
* **Tercihler** (`/bildirimler`): kategori × kanal (uygulama içi, e-posta). Varsayılan: uygulama içi
  açık, e-posta yalnızca güvenlikte açık. **Güvenlik bildirimi uygulama içinde kapatılamaz.**
* **E-posta:** tercih açıksa ve e-posta doğrulanmışsa `email_outbox` kuyruğuna yazılır. Gönderim
  sağlayıcısı bağlanana kadar (M-G6) "bekliyor" durumunda kalır.
* **Push bildirimi yok.** VAPID anahtarları ve gönderim altyapısı M-G6 ve dağıtım (M-G3) ile birlikte
  gelecek. PWA hazır olduğu için eklemek kolay.
* Başlıkta **bildirim zili**: okunmamış sayısı, son 8 bildirim, tümünü okundu sayma.
* **Sistem duyurusu** (`notifications.manage`, CONTENT_MANAGER/ADMIN/SUPER_ADMIN): tek sorguyla tüm
  aktif kullanıcılara gider, duyuruları kapatanlar hariç. Bağlantı yalnızca site içi yol olabilir
  (`javascript:` vb. reddedilir). Denetim kaydına yazılır.

## 4. İçerik yönetimi

* **SSS**: veritabanında (5 başlangıç sorusu); yönetimden ekleme, düzenleme, gizleme ve silme. Ana
  sayfa ve `/sss` buradan beslenir.
* **Sayfalar**: kullanım koşulları, gizlilik ve KVKK, mesafeli satış, ön bilgilendirme, çerezler.
  Başlangıçta **boş ve yayımlanmamış**. Hukuk onayı olmadan metin uydurulmadı. Yönetim
  panelinde yayımlarken "hukuki onay alındığından emin olun" onayı istenir; en az 50 karakter.
  Metin düz yazı olarak işlenir (HTML çalıştırılmaz).
* Alt bilgide yasal sayfa bağlantıları, SSS ve Paketler.
* Yönetim: **İçerik & Duyurular** (`content.manage` / `notifications.manage`).

## 5. PWA (telefona uygulama olarak ekleme)

* Manifest: 192/512 PNG ikonlar, maskable ikon, Apple touch ikonu, kısayollar (Maç Merkezi, Kupon
  Merkezi, Panelim), `standalone` görünüm.
* Servis çalışanı (`/sw.js`, yalnızca üretim derlemesinde):
  * **Canlı veri önbellekten sunulmaz.** API (`/v1`, `/admin`) ve sayfalar her zaman ağdan gelir.
    Ağ yoksa çevrimdışı sayfası gösterilir: "eski veriyi canlıymış gibi göstermemek için çevrimdışı
    içerik sunmuyoruz".
  * Değişmeyen statik dosyalar (`/_next/static`, ikon, font) önbellekten açılır. Sürüm değişince
    eski önbellek silinir.
* E2E testinde servis çalışanının sayfayı kontrol ettiği ve ağ kesikken çevrimdışı sayfasının
  geldiği doğrulanır.

## 6. Yeni / değişen

* API: `mi_api/engage/` (models, notify, scan, api), geçiş `0010_engage`. Kancalar: auth (giriş,
  parola, MFA), billing (abonelik verme, iade), kupon sonuçlandırma. Celery: `mi.notifications.scan`.
* Web: `components/engage.tsx` (zil, favori düğmesi), `components/widgets.tsx` (panel ızgarası),
  `/bildirimler`, `/sss`, `/yasal/[slug]`, `/yonetim/icerik`, `public/sw.js`, `public/offline.html`,
  PNG ikonlar, manifest.

## 7. Testler

| Dosya | Test | Kapsam |
|---|---|---|
| api `test_engage.py` | 4 | Favoriler (tekrarsız, bilinmeyen kayıt, favori maç listesi), panel düzeni (geçersiz/yinelenen bileşen reddi, varsayılana dönüş), etkinlik; ilk girişte uyarı yok, yeni IP'den girişte güvenlik bildirimi, kapatılamayan güvenlik tercihi, parola değişikliği bildirimi, okundu işaretleme, e-posta kuyruğu; paket etkin → kupon sonucu → favori maç başlıyor → abonelik bitiyor → maç sonucu (tarama tekrarında çoğaltma yok); duyuru (kapatan almaz, geçersiz bağlantı reddi, denetim); içerik (yayımlanmamış yasal metin gizli, kısa metin reddi, yayımlama, gizli SSS görünmez, yetki) |
| web E2E `engage.spec.ts` | 1 | Maçı kaydet + takımı favorile → panel bileşenlerinde görünür → düzenle (kaldır, boyut) → kaydet → yeniden yükle → geri ekle → parola değişikliği bildirimi zilde → tercihlerde güvenlik kilitli → SSS → yayımlanmamış yasal sayfa → manifest ikonları → servis çalışanı → çevrimdışı sayfası |

**Toplam: API 185/185, ML 37/37, web E2E 14/14** (gerçek PostgreSQL 16 + Redis 7). `ruff`,
`mypy --strict`, `tsc` strict, `next build`: temiz.

Not: E2E paketi tek koşuda 9 kayıt yapar; kayıt ucu IP başına saatte 10 ile sınırlıdır.
`e2e/reset-local.sh` sayaçları sıfırlar. Art arda koşularda önce bu betiği çalıştırın.

## 8. Eksikler

| Konu | Durum |
|---|---|
| E-posta gönderimi | **M-G6** (kuyruk hazır) |
| Push bildirimi | M-G6 + M-G3 (VAPID, gönderim servisi) |
| Yasal metinlerin içeriği | **M-G4** hukukçu |
| Sürükle-bırak ile bileşen taşıma | Klavye ve dokunmatik için erişilebilir yukarı/aşağı düğmeleri kullanıldı. Sürükle-bırak istenirse eklenebilir |
| Bildirim e-postalarının çoğaltma koruması (uygulama içi kapalıyken) | Uygulama içi bildirimi kapatan kullanıcıda e-posta yalnızca olay başına bir kez denenir; kuyruk tarafında ek tekilleştirme M-G6 entegrasyonuyla |
