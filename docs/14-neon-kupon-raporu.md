# Neon Light tasarım, sade menü ve kupon oluşturucu düzeltmeleri (2026-11-19)

Kullanıcı isteği: "Kupon oluşturmuyor; siteyi biraz kolaylaştır; tasarım açık ve neon olsun."

## 1. Kupon oluşturucu neden boş dönüyordu

Gerçek veride (football-data.org) üç neden üst üste geliyordu:

| Neden | Durum | Düzeltme |
|---|---|---|
| Hesabın paketi FREE | Kupon oluşturucu PRO/ELITE hakkı; FREE'de `plan_required` | `futbol.ps1 paket EPOSTA [PRO\|ELITE]` (ödemesiz, `mi-admin grant-plan`, denetime yazılır). Canlı ödeme (M-G5) açılmadı. |
| Yalnızca "Bugün / Yarın" | Ligler çoğunlukla hafta sonu oynar; hafta içi aday çıkmıyordu | `POST /v1/coupons/generate` yeni `days` alanı (1–7; varsayılan 1, geriye uyumlu). Web: Bugün / 3 gün / 7 gün, varsayılan 3 gün. |
| Güvenilirlik eşiği | Düşük risk ve Dengeli profiller yalnızca orta/yüksek güvenilirlikli tahminleri kullanır; gerçek modellerde güvenilirlik çoğunlukla düşük | Eşik **gevşetilmedi**. Hata mesajı sayılarla nedenini söylüyor (kaç maç tarandı, kaçı güvenilirlik yüzünden, kaçı olasılık bandı yüzünden elendi) ve öneri veriyor; web'de tek tıkla "Yüksek risk ile dene", "N−1 maçla dene", "7 günü tara". |

Web formu sadeleşti: piyasa seçimi "Gelişmiş" altına alındı (boş = tümü).

Testler (`api/tests/test_coupons_api.py`): neden dökümü ve öneri metni, boş aralıkta "maç yok", iki günlük
pencerenin ertesi günün maçlarını kapsaması, `days` üst sınırı (8 → 422).

## 2. Neon Light tasarımı

- **Tasarım:** Yeni varsayılan tasarım `neon-light`. Açık zemin üzerinde neon pembe (`away #ff2bd6`) ve camgöbeği (`home #00b8f0`) parıltı kullanılır.
- **Yazı renkleri:** Hepsi WCAG AA kontrast kapısından geçiyor (`design/contrast.py`). Vurgu rengi `#a00d8e`, beyaz üzerinde 7,1:1. Neon tonlar yalnızca süs olarak (parıltı, ışık lekeleri, başlık altı çizgi) kullanılır; metin rengi olarak kullanılmaz.
- **Şema:** Yeni gölge seçeneği `shadow: "neon"` eklendi (şema, web `ENUMS`/`SHADOWS`, `data-shadow` özniteliği ve CSS'te). Design Studio'da da seçilebilir.
- **Geçiş 0014:** Tasarım yayımlanmış v1 olarak eklenir. Varsayılan tasarım, **yalnızca** hâlâ ilk kurulum değeri `signature-black` ise `neon-light` yapılır. Yönetici panelden başka bir tasarım seçtiyse ya da kullanıcı kendi tasarımını seçtiyse bunlara dokunulmaz.
- **Geçiş doğrulaması:**
  - Eski kodla 0013'e kadar kurulan veritabanında 0014 tasarımı ekleyip varsayılanı değiştirdi; ikinci çalıştırma hiçbir şey yapmadı.
  - Yeni kurulumda tasarımı 0008 ekliyor, 0014 hiçbir şey yapmıyor.
  - Test, geçişteki sabit yapılandırmanın uygulamadaki varsayılanla aynı olduğunu ve kontrast kapısından geçtiğini doğruluyor.

## 3. Sadeleştirme

- **Ana menü:** Dört başlığa indi: Ana Sayfa · Tahminler · Kupon Oluştur · Başarı Oranı. Sanal Portföy, Paketler ve SSS alt bilgide.
- **Mobil:** Alt sekmeler aynı dört başlığı ve Giriş/Panelim'i gösterir.
- **Ana sayfa:** Ana düğmeler "Tahminleri gör" ve "Kupon oluştur".

## 4. Diğer

- `futbol.ps1 paket` komutu eklendi; kılavuz tablosu güncellendi.
- E2E testleri yeni menü adlarına ve 11 tasarıma göre güncellendi.

## 5. Sunucuda tema geçmemişti (düzeltildi)

Canlı sitede yeni menü gelmişti ama sayfa `data-design="signature-black"` ile çıkıyordu. Neden: Windows
başlatıcısı (`calistir.ps1`) web sürecine `MI_API_URL` vermiyordu. Bu yüzden sunucu tarafındaki tasarım
isteği varsayılan `127.0.0.1:8080` adresine gidiyor, ulaşamıyor ve yerleşik temaya sessizce düşüyordu.
Bu durum ilk kurulumdan beri vardı; yerleşik tema Signature Black olduğu için fark edilmemişti.

Düzeltmeler:
- `calistir.ps1` web sürecine `MI_API_URL=http://127.0.0.1:8081` verir.
- `next.config.ts`, derleme anındaki adresi (`MI_API_URL_BUILD`) yedek olarak koda gömer.
- `layout.tsx`, tasarımlar alınamazsa bunu günlüğe yazar.

Doğrulama: Paket `MI_API_URL` olmadan çalıştırıldı; sayfa `data-design="neon-light"` ile geldi.
