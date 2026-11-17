# Arayüz Raporu — Web Uygulaması (Faz 7 çekirdeği + Faz 9 başlangıcı)

> Durum: **Çalışan web uygulaması (kod + uçtan uca testler).** Gerçek API'ye bağlı; tasarım:
> DESIGN 01 — Signature Black. Diğer 9 tasarım, Design Studio ve ödeme sonraki fazlarda.

## 1. Mimari

* [`web/`](../web/): Next.js 16 (App Router), React 19, TypeScript (strict), Tailwind CSS 4, TanStack
  Query, React Hook Form + Zod, Recharts, lucide ikonları.
* **API aynı köken üzerinden vekil edilir** (`/v1/*`, `/admin/v1/*` → API). Tarayıcı yalnızca siteyle
  konuşur; oturum çerezleri birinci taraf ve `SameSite=Strict` kalır; API adresi ve sağlayıcı
  anahtarları tarayıcıya hiç gitmez.
* Güvenlik başlıkları: CSP (`connect-src 'self'`, `frame-ancestors 'none'`), `nosniff`,
  `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy`, üretimde HSTS.
* Tasarım tokenları CSS değişkeni olarak `[data-design]` altında tanımlı; bileşenler yalnızca
  token kullanır. Faz 8'deki diğer tasarımlar aynı token adlarını yeniden tanımlayacak + kendi yerleşim
  bileşenlerini getirecek.
* PWA: web manifest, uygulama ikonu, `theme-color`; mobilde alt gezinme çubuğu.
* Docker: `output: "standalone"`, root olmayan kullanıcı; `docker-compose` içinde `web` servisi.

## 2. Ekranlar

**Site (kullanıcı):**

| Yol | İçerik |
|---|---|
| `/` | Hero, bugünün canlı özeti (maç / AI analizi / çekimser / biten), günün maçları, öne çıkan analizler, model performansı (gerçek sonuç yoksa "veri yok"), yaklaşım (4 ilke), üyelik paketleri (**fiyat yok**, "yakında"), SSS |
| `/maclar` | Türkiye gününe göre gün şeridi, Tümü/Canlı/Başlamadı/Bitti filtreleri, lig filtresi, lig bazında gruplu maç listesi, satır içinde 1X2 olasılık çubuğu veya çekimserlik nedeni; canlı maç varken 30 sn'de bir yenileme |
| `/maclar/[id]` | Maç başlığı (skor kırılımı, stat, hakem, **kaynak, tazelik, veri tamlığı puanı**), sekmeler: **AI Analizi** (olasılık dağılımı + %10–%90 aralığı, güvenilirlik / veri kalitesi / modeller arası uyum / beklenen gol ayrı kartlarda, piyasalar, en olası skorlar, model bileşenleri ve ağırlıkları, uyarı metni), **İstatistikler** (xG dahil karşılaştırma), **Kadrolar** (ilk 11, yedekler, sakat/cezalı/şüpheli) |
| `/ligler/[id]` | Puan durumu (O-G-B-M-A-Y-AV-P, form) |
| `/performans` | Gerçekleşmiş performans (yalnızca sonuçlanmış tahminler), güvenilirlik diyagramı, yöntem açıklaması |
| `/kayit`, `/giris` (+ iki adımlı doğrulama adımı), `/eposta-dogrula`, `/sifremi-unuttum`, `/sifre-sifirla` | Hesap akışları; 18 yaş ve risk onayı |
| `/panel` | Hesap özeti, günün maçları + tahminler, **iki adımlı doğrulama kurulumu (QR + kurtarma kodları)**, açık oturumlar ve kapatma, KVKK hesap silme |
| `/risk` | Risk bildirimi (taslak; hukuk incelemesi M-G4) |

**Yönetim paneli (`/yonetim`, ayrı oturum, MFA zorunlu, menü izinlere göre):**

| Yol | İçerik |
|---|---|
| `/yonetim/giris` | E-posta + parola + doğrulama kodu |
| `/yonetim` | Command Center: Action Center uyarıları (sağlayıcı yok, başarısız veri işleri), kullanıcı sayısı, bugünkü/canlı maç, şampiyon model ve test log loss, takip edilen lig, son veri işleri, sağlayıcı kota bütçesi. Gelir metrikleri: **"ödeme altyapısı bağlı değil"** (sıfır veya uydurma rakam yok) |
| `/yonetim/veri` | Futbol Veri Merkezi: işi elle çalıştırma, lig takibi, senkronizasyon geçmişi |
| `/yonetim/modeller` | Model Lab: sürümler, test metrikleri (model başına), dışlanan modeller ve nedenleri, özellik önemi, Optuna özeti, aday–şampiyon farkı, şampiyon yapma / geri alma |
| `/yonetim/kullanicilar` | Arama, durum filtresi, sayfalama; kullanıcı ayrıntısı, askıya alma/etkinleştirme, rol atama, son etkinlik |
| `/yonetim/denetim` | Denetim kaydı (eylem öneki filtresi, sayfalama), **hash zinciri doğrulama** |

Hassas işlemler (askıya alma, rol atama, şampiyon değiştirme) API `reauth_required` döndürdüğünde
arayüz parola + kod penceresini açar, doğrulama sonrası işlemi otomatik tekrarlar.

## 3. Her bileşen durumu

Yükleniyor (iskelet), boş (açıklamalı), hata (tekrar dene), başarı, devre dışı, odak (görünür odak
halkası), `prefers-reduced-motion` desteği. Erişilebilirlik: içeriğe atla bağlantısı, `aria-current`,
`aria-selected`, `role="alert"`, olasılık çubuklarında metin alternatifi, form hatalarında
`aria-invalid` + `aria-describedby`.

## 4. Demo verisi (yalnızca geliştirme/test)

`ml/scripts/seed_demo.py`: kurgusal "Demo Süper Lig" (12 takım, 10 sezon), bugünkü/yarınki maçlar,
gerçek eğitim ve tahmin hattı. **`MI_ENVIRONMENT` staging/production ise çalışmayı reddeder.** Kaynak
"Demo verisi (test ortamı — gerçek değil)" olarak görünür ve sitede "Test ortamı: kurgusal demo
verisi" uyarısı çıkar. Demo modeli 257 maçlık test döneminde ECE 0.043 ile 4 maç için tahmin yayımladı,
2 maçta (modeller arası fark > %20) çekimser kaldı — bu rakamlar yalnızca sentetik veriye aittir.

## 5. Test sonuçları

| Kontrol | Sonuç |
|---|---|
| `tsc --noEmit` (strict) | Hatasız |
| `next build` | Başarılı |
| `npm audit` | 0 açık. İlk sürüm (16.4.3) GHSA-mfr8-8qww-v76h'den etkilendiği için yamalı 16.4.5'e geçildi |
| Playwright uçtan uca (gerçek API + PostgreSQL + Redis + demo verisi) | **6/6 geçti** |

E2E senaryoları:
1. Ana sayfa → maç merkezi → yayımlanmış tahminli maç (olasılık, güvenilirlik, uyum, uyarı, demo etiketi) → çekimser maç (masaüstü + mobil)
2. Model şeffaflığı ve risk bildirimi (masaüstü + mobil)
3. Kayıt → giriş → MFA kurulumu → çıkış → hatalı kodun reddi → iki adımlı giriş → oturum listesi
4. `mi-admin bootstrap` ile parolasız ilk süper yönetici → tek kullanımlık bağlantıyla parola → MFA → yönetim girişi → Command Center → veri işi çalıştırma → Model Lab → kullanıcı arama → denetim zincirini doğrulama

API 125/125, ML 32/32 testleri de bu sürümle yeniden çalıştırıldı ve geçti.

## 6. Eksikler (sonraki fazlar)

| Konu | Faz |
|---|---|
| Diğer 9 tasarım sistemi + Design Studio (önizleme, taslak, yayın, sürüm geçmişi) | 8 |
| Kupon merkezi, sanal bakiye ekranları | 4–5 |
| Abonelik/ödeme ekranları, plan bazlı kısıtlar | 6 |
| Dashboard widget kişiselleştirme (ekle/kaldır/taşı/boyut), favori takım/lig, bildirimler | 7 (devam) |
| Admin: kalan modüller (finans, abonelik, içerik, bildirim, API, lisans, ayarlar, yedekleme, Data Explorer, özellik bayrakları, Ctrl+K komut paleti) | 9 |
| WebSocket ile anlık skor (şu an 30 sn'de bir yenileme) | 7 (devam) |
| Lighthouse / axe otomatik denetimi | 10 |
| Web Docker imajı | Bu ortamda Docker daemon'ı yok; CI'da derleniyor |
