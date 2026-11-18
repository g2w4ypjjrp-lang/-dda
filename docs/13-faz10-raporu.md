# Faz 10 Raporu — Yayın Öncesi: Güvenlik, Yedekleme, İzleme, Dağıtım Hazırlığı

> Durum: **Tamamlandı (kod + testler + belgeler).** Gerçek sunucuya dağıtım yapılmadı: alan adı ve
> bulut sağlayıcısı kararı (M-G3) sizde. Üretim yığını, TLS vekili ve çalıştırma kılavuzu hazır ve
> araçlarla doğrulandı; onay verdiğinizde [çalıştırma kılavuzu](calistirma-kilavuzu.md) adım adım
> uygulanır.

## 1. Dört göz onayı (kritik işlemler)

`dual_control` bayrağı açıkken aşağıdaki işlemler **hemen yürütülmez**; bir onay talebi açılır (HTTP 202)
ve aynı izne sahip **başka** bir yönetici onaylayınca yürütülür.

| İşlem | İzin |
|---|---|
| Ödenmiş siparişi iade | `finance.refund` |
| İncelemedeki siparişi onayla / iade et | `finance.refund` |
| Kullanıcının yönetici rollerini değiştir | `roles.assign` |
| Dört göz kuralını kapatmak | `flags.manage` |

* Onaylayan; talep sahibi olamaz (veritabanında da `CHECK`), aynı izne sahip olmalı ve hassas izinlerde
  son dakikalarda parola + MFA ile yeniden doğrulamış olmalı.
* Onayda işlem, **o anki durum yeniden denetlenerek** yürütülür (talep ile onay arasında sipariş
  değişmiş olabilir). Hata olursa kayıt noktası geri alınır, hiçbir yan etki kalmaz ve talep
  `failed` olarak, nedeniyle kapanır.
* Talep 24 saatte düşer; talep sahibi iptal edebilir; aynı hedefe aynı işlem için tek bekleyen talep.
* Karara bağlanan talep **değiştirilemez ve silinemez** (veritabanı tetikleyicisi).
* Kuralın kapatılması da onaya tabidir: tek bir yönetici önce kuralı kapatıp sonra tek başına iade
  yapamaz.
* Her adım denetim kaydında (`approval.requested/executed/rejected/cancelled/failed`); yürütülen
  işlemin kendi kaydı (`billing.refunded`, `admin.roles_changed`…) talep numarasını taşır.
* Varsayılan **kapalı**: tek yöneticili bir kurulumda açılırsa iade yapılamaz hale gelir. Önerilen:
  ikinci yönetici atandıktan sonra açmak (kılavuz §3).
* Arayüz: **Yönetim → Onaylar (dört göz)** (bekleyen / karara bağlanan; onayla, reddet — not zorunlu,
  iptal), Action Center'da bekleyen talep uyarısı; iade/rol/bayrak ekranlarında "onaya gönderildi"
  bildirimi.

## 2. Yedekleme, doğrulama, geri yükleme

* `mi-admin backup` ve işçide günlük `mi.backup` (03:17 UTC): `pg_dump` (custom biçim), önce `.part`,
  bitince yeniden adlandırma, SHA-256 yan dosyası, `backups` tablosu, son N yedeği tutma.
* **Gerçek doğrulama:** her yedek geçici bir veritabanına geri yüklenir; şema sürümü, tablo sayısı,
  temel satır sayıları ve **denetim kaydı hash zinciri** orada denetlenir; geçici veritabanı her
  durumda silinir. `CREATE DATABASE` yetkisi yoksa sonuç bunu söyler ve yedek doğrulanmış sayılmaz.
* `mi-admin restore`: önce özeti doğrular (tutmazsa hiçbir şey yapmaz), tek işlemde yükler; çalışan
  veritabanının üzerine yalnızca `--overwrite-current` ile.
* Uyarılar (Action Center + Prometheus): yedek başarısız, 26 saattir başarılı yedek yok, doğrulama
  başarısız, üretimde yedek yapılandırılmamış.
* Arayüz: **Yönetim → Yedekler** (geçmiş, boyut, özet, doğrulama ayrıntısı). Panelden geri yükleme
  bilinçli olarak yok.
* API imajına PostgreSQL 16 istemcisi eklendi (`pg_dump` sunucuyla aynı ana sürüm olmalı). İmaj bu
  ortamda derlendi; içinde `pg_dump 16.16` ve root olmayan kullanıcı doğrulandı.

## 3. İzleme

* `GET /metrics` (Prometheus metin biçimi), yalnızca `MI_METRICS_TOKEN` ile; jeton yoksa uç 404.
  Ölçüler: bileşen sağlığı, veritabanı gecikmesi, kuyruk derinliği, işçi kalp atışı yaşı, 1/5/60
  dakikalık istek–5xx–gecikme, kullanıcı ve etkin abonelik sayısı, bekleyen onaylar, yedek durumu.
  **Bilinmeyen değer yazılmaz** (ör. kalp atışı hiç alınmadıysa yaş ölçüsü yok; sıfır uydurulmaz).
* `deploy/prometheus/`: örnek yapılandırma ve 11 uyarı kuralı — `promtool check rules` ile doğrulandı.
* Caddy `/metrics`, `/docs` ve `/openapi.json` yollarını dışarıya 404 döner.

## 4. Otomatik güvenlik taraması

`api/tests/test_security_sweep.py` uygulamadaki **her rotayı** (135) dolaşır; yeni bir rota
eklendiğinde kendiliğinden kapsanır:

1. **Statik politika:** her `/admin/v1` rotası yönetici oturumu ister; durum değiştiren her yönetim
   rotası ya izin ister ya da gerekçesiyle listelenmiştir; herkese açık her rota açık bir listededir
   (yeni açık rota = bilinçli karar).
2. **Anonim:** açık olmayan her rota 401 (100+ rota).
3. **Üye oturumu:** yönetim API'sine geçmez (ayrı çerez).
4. **İzinsiz personel:** izin isteyen her rota 403 (SUPPORT rolüyle 40+ rota); reddedilen isteklerin
   hiçbiri denetim kaydına iz bırakan bir işlem yapmadı.
5. **Enjeksiyon:** tüm GET rotalarının metin parametrelerine SQL, şablon, yol, NUL ve çok uzun girdiler
   (40+ deneme × 6 girdi): hiçbir 5xx yok; kullanıcı tablosu ve denetim zinciri sağlam.
6. **Başlıklar:** her yanıtta `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, `no-store`,
   `X-Request-ID` ve yeni eklenen `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
7. Toplu atama (kayıtta rol/durum/doğrulama alanları yok sayılır), 256 KB gövde sınırı, iç içe JSON
   sınırı, başka kökenden durum değiştiren istek (CSRF) reddi.

**Bulunan ve düzeltilen açık:** yol, sorgu dizesi veya JSON gövdesindeki NUL baytı (`%00`,
`\u0000`) PostgreSQL'de hata verip **500**'e yol açıyordu (ör. denetim kaydı filtresi). Artık istek
koruması bunları uygulamaya ulaşmadan 400 ile reddediyor; testli.

## 5. Bağımlılık denetimi

| Kapsam | Araç | Sonuç |
|---|---|---|
| API (Python, üretim) | pip-audit | Bilinen açık yok |
| ML (Python, üretim) | pip-audit | Bilinen açık yok |
| Web üretim bağımlılıkları | `npm audit --omit=dev` | 0 açık |
| Web geliştirme araçları | `npm audit` | 5 yüksek: `picomatch` ReDoS (GHSA-fc5q-39xc-vjpf) — yalnızca `vitest`/`vite` zincirinde |

Geliştirme zincirindeki uyarı için yamalı sürüm yok (önerilen "düzeltme" vitest'i eski sürüme
indirmek); bu paketler üretim imajına girmez ve yalnızca bizim yazdığımız dosya kalıplarını işler.
Kabul edilen risk olarak kaydedildi; yamalı sürüm çıkınca güncellenecek. CI'a web üretim
bağımlılıkları için `npm audit --omit=dev --audit-level=high` eklendi (Python denetimi zaten vardı).

## 6. Performans

**Yük testi** (`api/scripts/loadtest.py`): herkese açık 11 okuma ucu, 20 eşzamanlı istemci, 30 sn,
tek API süreci, demo verili yerel veritabanı (1.329 maç):

| İstek | İstek/sn | 5xx | Diğer 2xx dışı | p50 | p95 | p99 | En uzun |
|---|---|---|---|---|---|---|---|
| 11.088 | 369 | 0 | 0 | 55 ms | 83 ms | 100 ms | 186 ms |

En yavaş uçlar maç listesi ve tahminler (p95 ≈ 93 ms). Sonuç yalnızca bu makine ve veri hacmi için
geçerlidir; üretim kapasitesi dağıtımdan sonra aynı betikle ölçülmelidir.

**İndeks incelemesi:** sık sorgu kalıpları `enable_seqscan=off` ile "kullanılabilir indeks yolu var mı?"
diye EXPLAIN edildi. Bulgular ve geçiş 0012:

| Sorgu | Sorun | Çözüm |
|---|---|---|
| Yeni IP'den giriş uyarısı (son 90 gün oturumlar) | Kısmi indeks yalnızca açık oturumları kapsıyordu → tam tarama | `user_sessions (user_id, created_at)` |
| Denetim kaydı: yalnızca `actor_id` / `target_id` | İndeksin ilk sütunu değil → tüm indeks taranıyordu | `(actor_id, id DESC)`, `(target_id, id DESC)` |
| Denetim kaydı: eylem öneki (`auth.%`) | Harmanlama C değilse btree önek araması yok | `action text_pattern_ops` (kullanılabildiği doğrulandı) |
| "Abonelik bitiyor" taraması | İlgisiz indeks taranıyordu | `subscriptions (current_period_end) WHERE status='active'` |

## 7. Görsel karşılaştırma testleri

`web/e2e/visual.spec.ts` — isteğe bağlı (`E2E_VISUAL=1`), masaüstü + mobil, içeriği güne göre
değişmeyen 6 sayfa (giriş, kayıt, şifremi unuttum, SSS, risk bildirimi, yönetim girişi). Referanslar
`e2e/visual.spec.ts-snapshots/` içinde; %1 piksel toleransı. Farkı yakaladığı doğrulandı (bir
referans bilerek değiştirildiğinde %2 farkla başarısız oldu). Tasarım değişikliğinde
`--update-snapshots` ile yenilenir ve fark gözden geçirilir. Maç/tahmin sayfaları tarihe bağlı olduğu
için kapsam dışı.

## 8. Üretim yığını

* `docker-compose.prod.yml`: Caddy (otomatik Let's Encrypt, HTTP/3, HSTS), web, api, migrate, worker
  (yedek birimi), beat; isteğe bağlı `ml` ve `monitoring` profilleri. Kapsayıcılar root olmayan
  kullanıcı, salt okunur kök dosya sistemi, `no-new-privileges`, tüm yetenekler düşürülmüş.
* Veritabanı ve Redis yönetilen hizmet (TLS); uygulama üretimde güvensiz ayarla açılmıyor.
* İstemci IP zinciri: Caddy `X-Forwarded-For`'u gerçek istemci IP'siyle **ezer** (sahteleme yok) →
  Next.js vekili başlığı değiştirmeden iletir (kaynak kodda doğrulandı) → API yalnızca web
  kapsayıcısının sabit adresine güvenir.
* `.env.prod.example`: tüm üretim değişkenleri; gizli dosyalar `.gitignore`'da.
* Doğrulama: `docker compose config` (tüm profiller), `caddy validate`, `promtool check rules`
  (üçü CI'a da eklendi). API imajı bu ortamda derlendi (`/backups` dizini `mi` kullanıcısına ait,
  `pg_dump 16.16`). Web imajı da derlendi (ilk denemede Docker Hub çekme sınırına takılmıştı) ve
  salt okunur kök dosya sistemiyle, `uid 10001` kullanıcısıyla açılıp güvenlik başlıklarıyla yanıt
  verdiği doğrulandı.
* **Yapılmadı:** üretim yığınının bir sunucuda uçtan uca ayağa kaldırılması (TLS sertifikası gerçek
  alan adı ister) — M-G3 sonrası kılavuzdaki "İlk gün denetim listesi" ile yapılacak.

## 9. Testler

| Takım | Sonuç |
|---|---|
| API (pytest, gerçek PostgreSQL 16 + Redis 7) | **200 / 200** (Faz 10 ile +15: dört göz 3, yedek 2, metrik 1, güvenlik taraması 5, renk kontrastı 2, anahtar döndürme 2) |
| ML (pytest) | **37 / 37** |
| Web tip denetimi + üretim derlemesi | Temiz |
| E2E (Playwright, gerçek API + DB) | **17 / 17**, atlanan yok (dört göz + yedekler akışı; erişilebilirlik: herkese açık sayfalar, 10 tasarım, oturumlu sayfalar, 19 yönetim modülü) |
| Görsel karşılaştırma (isteğe bağlı) | **12 / 12** (6 sayfa × masaüstü/mobil) |
| ruff, ruff format, mypy (API, ML) | Temiz |

**E2E saat bağımlılığı (düzeltildi):** demo tohumu yaklaşan maçları "şimdi + 2 saat"e koyuyordu;
Türkiye saatiyle 22:00'den sonra bu maçlar ertesi güne kaydığı için "bugün"e bakan 4 test atlanıyordu
(başarısız değil, atlanıyordu). Tohum artık geç saatte yaklaşan maçları yarına ve ertesi güne
yerleştiriyor; ana sayfa testi bugün ve yarına bakıyor. CI hangi saatte koşarsa koşsun aynı testler
çalışır.

## 10. Ek çalışma: erişilebilirlik, Lighthouse, anahtar döndürme

### Erişilebilirlik (axe, WCAG 2.1 AA)

`web/e2e/a11y.spec.ts` + akış testlerinin içinde: 14 herkese açık sayfa, **10 tasarımın her biri**
(5 sayfa), oturumlu kullanıcı sayfaları (panel, bildirimler, sanal portföy, kupon merkezi) ve
**19 yönetim modülünün tamamı**. Sıfır ihlal hedefi; her E2E koşusunda denetleniyor.

Bulunan ve düzeltilenler:

| Bulgu | Etki | Düzeltme |
|---|---|---|
| 10 tasarımdan 6'sında soluk metin 4,5:1 eşiğinin altında (3,1–4,4) | Ciddi | Varsayılan renkler düzeltildi; genişletilmiş denetimle (her metin rengi × her yüzey + rozet zeminleri) 9 tasarımda renk ayarı |
| Kontrast kuralı yoktu: Design Studio'da erişilemez renk yayımlanabiliyordu | Ciddi | `design/contrast.py`: eşik altı tasarım **yayımlanamaz** ve böyle bir eski sürüme **geri dönülemez** (422); editörde canlı uyarı ve "Yayınla" kapalı |
| Yayındaki sürümler değiştirilemez | — | Geçiş 0013: düzeltme yeni sürüm olarak yayımlanır, eski sürüm arşivde; yöneticinin değiştirdiği renge dokunulmaz (eski durumdaki veritabanında doğrulandı) |
| Vurgu tonlu zeminde (seçili kart, okunmamış satır) soluk metin | Ciddi | `tone-highlight` sınıfı: bu zeminlerde soluk metin ikincil metne çıkar |
| Logo bağlantısının adı görünen metinle uyuşmuyordu (her sayfada) | Ciddi | Görsel logo gizlendi, tek tip okunur ad |
| Bildirim zilinde görünen sayı adın parçası değildi | Ciddi | Ad görünen içerikten oluşuyor ("Bildirimler 1 okunmamış") |
| Metin içi bağlantı yalnızca renkle ayırt ediliyordu | Ciddi | Altı çizili |
| Maç sayfasında `h1` yoktu; yönetim girişinde ana bölge (`main`) yoktu | Orta | Eklendi |

### Lighthouse (12.8, mobil, yavaş 4G + 4× CPU benzetimi, yerel üretim derlemesi)

| Sayfa | Performans | Erişilebilirlik | En iyi uygulamalar | SEO | LCP | TBT |
|---|---|---|---|---|---|---|
| Ana sayfa | 76 | 100 | 96 | 100 | 4,0 sn | 420 ms |
| Maç Merkezi | 83 | 100 | 96 | 100 | 3,7 sn | 270 ms |
| Maç detayı | 86 | 100 | 96 | 100 | 3,1 sn | 330 ms |
| Paketler | 80 | 100 | 96 | 100 | 3,9 sn | 320 ms |
| Giriş | 90 | 100 | 93 | 100 | 2,7 sn | 270 ms |

* **Performans zayıf yanı:** sayfa verisi tarayıcıda, JavaScript yüklendikten sonra çekiliyor; en
  büyük içerik (LCP) bu yüzden geç çiziliyor (hedef ≤ 2,5 sn). Önerilen iyileştirme: ana sayfa ve
  Maç Merkezi verisini sunucuda önceden çekip sayfayla göndermek (React Query hydration). Bu
  çalışmada yapılmadı.
* En iyi uygulamalarda puan kaybı: oturumsuz ziyarette `/v1/auth/me` 401 döndüğü için tarayıcı
  konsolunda hata görünüyor; giriş sayfasında bir CSP uyarısı (ayrıntısız) kaydedildi.

### Gizli anahtar döndürme

`mi-admin rotate-kek [--dry-run]` (`mi_api/ops/keys.py`): MFA sırları tek işlemde eski anahtardan
yenisine taşınır; tek bir sır bile çözülemezse hiçbir şey değişmez; tekrar çalıştırmak güvenli.
Yeni anahtar ortam değişkeniyle verilir. Ayrıca bulunan sorun: sunucu yanlış anahtarla çalışırsa MFA
girişi **500** veriyordu; artık nedenini günlüğe yazan **503** dönüyor. Adımlar kılavuzda (§9).

## 11. Açık kalanlar (dürüst liste)

| Konu | Durum | Bekleyen |
|---|---|---|
| Gerçek dağıtım, alan adı, TLS sertifikası | Dosyalar hazır, doğrulandı; sunucu yok | **M-G3** kararınız |
| Gerçek futbol verisi ve gerçek model metrikleri | Altyapı hazır; demo verisi yalnızca test ortamında | **M-G1** |
| Oran verisi ve EV | EV gösterilmiyor | **M-G2** |
| Yasal metinler (KVKK, gizlilik, koşullar, çerez, mesafeli satış) | Boş ve yayımlanmamış | **M-G4** |
| Canlı ödeme | Test modu | **M-G5** |
| E-posta ve push gönderimi | Kuyruğa yazılıyor, gönderilmiyor | **M-G6** |
| Üretim kapasite ölçümü | Yalnızca yerel ölçüm | Dağıtım sonrası |
| Maliyet metrikleri (API/sunucu) | Bağlı değil; panel "veri yok" diyor | Dağıtım sonrası |
| İlk yarı piyasaları | Demo verisinde kalibrasyon kapısını geçmiyor (eşik gevşetilmedi) | Gerçek veri (M-G1) |
| Mobil sayfa performansı (LCP 2,7–4,0 sn) | Ölçüldü; sunucu tarafı veri ön yükleme önerildi | Sonraki çalışma |
| Oturumsuz `/v1/auth/me` 401'inin konsolda hata görünmesi | Ölçüldü | Sonraki çalışma |
