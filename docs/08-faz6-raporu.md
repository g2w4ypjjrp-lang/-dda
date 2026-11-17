# Faz 6 Raporu — Paketler, Abonelik, Ödeme ve Lisans

> Durum: **Tamamlandı (kod + testler).** Ödeme altyapısı test modunda çalışır. **Canlı ödeme kapalıdır**
> ve M-G5 onayı (şirket bilgileri, sağlayıcı sözleşmesi) olmadan açılamaz: `MI_PAYMENTS_TEST_MODE=false`
> yalnızca `MI_PAYMENTS_LIVE_ALLOWED=true` ile kabul edilir. Fiyat tanımlanmadıkça satış kapalıdır;
> sistemde hiçbir uydurma fiyat, gelir veya abone sayısı yoktur.

## 1. Tamamlanan işler

| Alan | Uygulama |
|---|---|
| Paketler | FREE / PRO / ELITE veritabanında. Haklar (`plan_entitlements`) yönetim panelinden değiştirilebilir, tip ve aralık kontrolüyle (bilinmeyen anahtar, aralık dışı değer reddedilir) |
| Hak kontrolü (backend) | Oturumsuz ziyaretçi FREE sayılır. **FREE:** yalnızca maç sonucu (1X2) olasılığı — diğer piyasalar, doğru skor, beklenen gol, belirsizlik aralığı ve bileşen modeller sunucudan **hiç gönderilmez**; kilitli alanlar ve gerekli paket listelenir. Kupon oluşturucu PRO'da; kupondaki maç sayısı ve günlük üretim sınırı pakete göre; kesirli Kelly ELITE'te; kupon geçmişi FREE 7 gün / PRO 90 gün. Ham skor matrisi hiçbir pakette dışarı verilmez |
| Günlük kullanım | `usage_daily` sayacı (Türkiye günü, atomik upsert); sınır aşılınca 429 `daily_limit`, sayaç geri alınır |
| Abonelik | Kaynak: ödeme, lisans veya yönetici (veritabanı kısıtıyla tutarlı). Aynı pakette etkin abonelik varsa yeni dönem eskinin **bitişinden** başlar. Süre bitince kullanıcı kendiliğinden FREE'ye düşer. Birden fazla etkin abonelikte en yüksek paket geçerli. **Otomatik yenileme yok** (tek seferlik ön ödemeli dönem) |
| Sipariş | Fiyat yoksa 409 `price_not_set`, sağlayıcı yoksa 503 `sales_closed`. E-posta doğrulaması, kullanım koşulları + mesafeli satış onayları zorunlu; onaylar zaman ve IP ile siparişe yazılır. Kullanıcı başına saatte 10 sipariş denemesi |
| Ödeme sağlayıcıları | **Simülatör** (yalnızca development/test; staging/production'da yapılandırma hatası), **PayTR** (iFrame token, `MI<sipariş no>`, HMAC bildirim, iade), **iyzico** (IYZWSv2 imzalı istek, checkout form, sonuç sorgulama, iade). Uyarlayıcılar AI Trading Intelligence projesinin test edilmiş ödeme modülünden taşındı |
| Bildirim güvenliği | İmzasız / yanlış imzalı bildirim **hiçbir şeyi değiştirmez** ama kaydedilir (400). Aynı olay (sağlayıcı + olay kimliği) bir kez işlenir: benzersiz indeks + sipariş satır kilidi + savepoint. Tutar/para birimi uyuşmazlığında abonelik verilmez, sipariş "incelemede". Aynı siparişe ikinci başarılı ödeme abonelik vermez, not düşer. `payment_events` değiştirilemez (tetikleyici). PayTR'ye düz `OK` yanıtı; iyzico tarayıcı dönüşünde sonuç sağlayıcıdan imzalı istekle alınır |
| İade | Yalnızca `finance.refund` (hassas izin → yeniden doğrulama). Sağlayıcı üzerinden; başarılıysa sipariş "iade edildi" ve bağlı abonelik hemen sona erer |
| Lisans anahtarları | `MI-XXXX-XXXX-XXXX-XXXX` (Crockford Base32, 80 bit). Veritabanında **HMAC-SHA256(pepper)** özeti + son 4 karakter; düz metin yalnızca üretimde bir kez gösterilir. Kullanım hakkı sınırı, son kullanma tarihi, iptal. Küçük harf / boşluk / I-L-O karışıklığı tolere edilir. Kullanıcı başına 15 dakikada 5, IP başına saatte 20 deneme; başarısız denemeler denetim kaydına yazılır. Geçersiz/iptal/dolu anahtar aynı genel hatayı verir (bilgi sızdırmaz) |
| Yönetim | Paket hakları ve fiyat (`subscriptions.manage`), ödemesiz abonelik tanımlama / sonlandırma, abonelik listesi (`subscriptions.read`), siparişler ve gelir özeti (`finance.read`), iade (`finance.refund`), lisans üretme/iptal (`licenses.manage`) ve listeleme (`licenses.read`). Tüm değişiklikler denetim kaydında |
| Gelir özeti | Yalnızca **test olmayan** gerçek siparişlerden: brüt/iade/net gelir, MRR/ARR (geçerli ödeme aboneliklerinin aylık karşılığı), 30 günlük ARPU ve kayıp oranı, etkin abonelik dağılımı, ödeme olayı sonuçları (sahte imza sayısı dahil), incelemedeki sipariş sayısı. Kayıt yoksa değer `null` → arayüzde "Veri yok" |
| CLI | `mi-admin grant-plan --email --plan PRO|ELITE --days N` (destek/test; denetim kaydına yazılır) |

## 2. Yeni tablolar (geçiş 0006)

`plans`, `plan_entitlements`, `plan_prices` (paket+dönem başına tek etkin fiyat), `orders`,
`payment_events` (yalnızca ekleme), `subscriptions`, `licenses`, `license_activations`, `usage_daily`.

## 3. API

Kullanıcı: `GET /v1/billing/plans`, `GET /v1/billing/me`, `POST /v1/billing/checkout`,
`GET /v1/billing/orders/{id}`, `POST /v1/billing/licenses/redeem`,
`GET /v1/billing/simulator/session`, `POST /v1/billing/simulator/complete` (yalnızca simülatör).

Sağlayıcı: `POST /v1/billing/webhooks/{simulator|paytr|iyzico}` (köken denetimi yok, imza zorunlu).

Yönetim (`/admin/v1/billing`): `GET plans`, `PUT plans/{kod}/entitlements`, `PUT plans/{kod}/prices`,
`DELETE plans/{kod}/prices/{dönem}`, `GET subscriptions`, `POST subscriptions/grant`,
`POST subscriptions/{id}/revoke`, `GET orders`, `POST orders/{no}/refund`, `GET/POST licenses`,
`POST licenses/{id}/revoke`, `GET summary`.

Değişen: `/v1/predictions*` artık paket haklarına göre daraltılır ve `access` alanı döner;
kupon ve sanal portföy uçları paket kontrolü yapar.

## 4. Arayüz

* **Paketler** (`/paketler`): üç paket, aylık/yıllık seçimi, fiyat varsa fiyat yoksa "Fiyat yakında",
  satış kapalı / test modu uyarısı, hak karşılaştırma tablosu (veritabanındaki güncel değerler),
  fatura bilgisi + iki zorunlu onay kutusu ile ödeme formu.
* **Test ödeme sayfası** (`/odeme/test`): büyük "TEST MODU — gerçek ödeme alınmaz" uyarısı, başarılı /
  başarısız seçimi (imzalı test bildirimi olarak işlenir).
* **Ödeme sonucu** (`/odeme/sonuc`): bildirim gelene kadar kısa aralıkla sorgular; ödendi / bekliyor /
  incelemede / başarısız.
* **Panelim:** paket, dönem bitişi, bugünkü kullanım, lisans anahtarı kullanma, siparişler, abonelik geçmişi.
* **Maç detayı:** FREE'de kilitli bölümler "PRO paketinde açılır" kartıyla; kupon/sanal hatalarında
  "Paketleri incele" bağlantısı.
* **Yönetim:** "Paketler & Abonelikler" (hak ve fiyat düzenleme, ödemesiz abonelik, liste/sonlandırma)
  ve "Finans & Lisanslar" (gelir özeti, siparişler ve iade, lisans üretme — anahtarlar bir kez gösterilir).

## 5. Test sonuçları

| Dosya | Test | Kapsam |
|---|---|---|
| api `test_billing.py` | 13 | FREE kısıtı (tahmin daraltma, kupon, Kelly) ve PRO maç sayısı sınırı; günlük sınır ve hak düzenleme (yetki, doğrulama, denetim); satış kapalı / fiyat yok / onay eksik / e-posta doğrulanmamış; simülatörle ödeme → abonelik → süre uzatma, başkasının oturumu, sahte oturum, sonuçlanmış sipariş, başarısız ödeme; sahte imza, tekrar gelen bildirim, ikinci ödeme, tutar uyuşmazlığı, bilinmeyen sipariş, değiştirilemez olay kaydı; iade (yetki, tekrar iade reddi, abonelik sonu, gelir özetinde test ödemeleri hariç); yönetici abonelik/fiyat işlemleri ve süre bitiminde FREE; lisans (pepper yoksa kapalı, bir kez gösterim, özet saklama, kullanım sınırı, iptal, tekrar kullanım, hız sınırı, denetim); PayTR token/imza vektörleri ve API üzerinden bildirim (`OK`, idempotent); iyzico imzalı istek, tarayıcı dönüşü, doğrulanamayan sonuç; canlı mod ve üretimde simülatör yapılandırma kilitleri |
| api (güncellenen) | — | Kupon ve sanal portföy testleri artık paket verilmiş kullanıcıyla çalışır |
| web E2E `billing.spec.ts` | 1 | Paketler sayfası (fiyat / "Fiyat yakında") → onaysız ödeme düğmesi kapalı → test ödeme sayfası → "Ödendi" → panelde ödemeyle gelen PRO |
| web E2E (güncellenen) | — | Kupon ve sanal portföy akışları `mi-admin grant-plan` ile PRO kullanıcıyla |
| Yönetim sayfaları (web) | — | Arkalarındaki uçlar API testleriyle doğrulandı; sayfalar için tarayıcı E2E testi **henüz yok** (derleme ve tip kontrolü temiz) |

**Toplam: API 161/161, web E2E 9/9** (gerçek PostgreSQL 16 + Redis 7; ML paketi bu fazda
değişmedi, 32/32). `ruff`, `mypy --strict`, `tsc` strict, `next build`: temiz.

## 6. Güvenlik notları

* Hak kontrolü yalnızca sunucuda; kilitli veri istemciye hiç gönderilmez (arayüzde gizlenmez).
* Ödeme bildirimleri imzasız işlenmez; sahte istekler de iz bırakır ve gelir özetinde sayılır.
* Simülatör üretim benzeri ortamda yapılandırma aşamasında reddedilir; canlı mod M-G5 bayrağı ister.
* Lisans düz metni saklanmaz; pepper değişirse eski anahtarlar geçersiz olur (belgelendi).
* Fiyat, hak, abonelik, iade ve lisans işlemleri hassas izin + yeniden doğrulama + denetim kaydı.

## 7. Eksikler ve onay bekleyenler

| Konu | Durum |
|---|---|
| Canlı ödeme, gerçek fiyatlar | **M-G5** (şirket bilgileri, PayTR/iyzico sözleşmesi) — kod hazır, test modunda doğrulandı |
| Mesafeli satış sözleşmesi ve ön bilgilendirme metinleri | **M-G4** hukuk onayı; onay kutuları ve kayıt hazır, metin sayfaları bekliyor |
| Fatura / e-arşiv entegrasyonu | Sağlayıcı seçimi gerekli (M-G5 ile) |
| Otomatik yenilenen abonelik (kart saklama) | Bilinçli olarak yok; istenirse sağlayıcının abonelik API'siyle ayrı iş |
| Ödeme e-postaları (makbuz, süre bitiyor) | **M-G6** e-posta sağlayıcısı |
| Sipariş incelemesi için yönetim akışı (onayla / reddet) | Faz 9 Action Center |

## 8. Sıradaki

İlk yarı skor modeli ve İY piyasaları; maç sayfasından "kupona ekle"; ardından Faz 8 (tasarım sistemleri)
ve Faz 9 (yönetim modülleri).
