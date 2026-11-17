# Match Intelligence AI — 01. Geliştirme Yol Haritası

Her faz şu sırayla ilerler: teknik analiz → mimari → veritabanı → backend → API → frontend →
güvenlik → test → hata düzeltme → rapor. Bir faz, kabul kriterleri **gerçek testlerle** sağlanmadan
"tamamlandı" sayılmaz. Dış hesap, para veya hukuki karar gerektiren adımlar onay kapısında bekler.

## Onay kapıları (sizin kararınız olmadan geçilmez)

| Kod | Konu | Ne zaman | Bekleyen karar |
|---|---|---|---|
| **M-G1** | Futbol veri sağlayıcısı aboneliği ve API anahtarı | Faz 2 | Sağlayıcı + paket seçimi (aşağıdaki karşılaştırma) |
| **M-G2** | Lisanslı oran verisi | Faz 4 | Sağlayıcı; yoksa EV/CLV hiç gösterilmez |
| **M-G3** | Alan adı, bulut sağlayıcısı, üretim dağıtımı | Faz 10 | Trading ile aynı alan adı kullanılmamalı (çerez ayrımı) |
| **M-G4** | Hukuki inceleme: KVKK metinleri, abonelik sözleşmesi, bahis/şans oyunları mevzuatı karşısında konumlandırma | Faz 6 öncesi | Hukukçu onayı |
| **M-G5** | Canlı ödeme (PayTR / iyzico / Stripe) | Faz 6 | Şirket bilgileri, sağlayıcı sözleşmesi |
| **M-G6** | E-posta / push sağlayıcısı | Faz 6-9 | Sağlayıcı ve gönderen alan adı |

## Mimari (özet)

```
api/        FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16 + Redis   (Faz 1-)
            (Celery işçisi ve Beat programı api paketinde: mi_api.worker — Faz 2)
ml/         Özellik mühendisliği, modeller, Optuna, kalibrasyon, backtest, ML işçisi (Faz 3)
web/        Next.js + TypeScript + Tailwind + shadcn/ui + TanStack Query (Faz 7-)
deploy/     Üretim dağıtım belgeleri (Docker Compose kökte, yerel geliştirme için)
```

* **Zaman:** veritabanında her zaman UTC (`timestamptz`), arayüzde `Europe/Istanbul`.
* **Kaynak izi:** her futbol kaydında `source`, `source_id`, `fetched_at`, `source_updated_at`.
* **Değiştirilemezlik:** yayımlanan tahmin ve kupon kayıtları, denetim kaydı gibi tetikleyiciyle
  korunur; tahmin anındaki model sürümü ve veri anlık görüntüsünün özeti saklanır.
* **Yetki:** her kontrol backend'de (`require_permission`); arayüz yalnızca gizler.

## Fazlar

| # | Faz | Durum |
|---|---|---|
| 1 | Teknik temel: mimari, veritabanı, kimlik doğrulama, MFA, RBAC, denetim kaydı, loglama | ✅ Tamamlandı ([rapor](02-faz1-raporu.md)) |
| 2 | Futbol verileri: sağlayıcı uyarlayıcısı, lig/takım/maç/istatistik, canlı veri, veri kalitesi | ✅ Altyapı tamamlandı ([rapor](03-faz2-raporu.md)); gerçek veri M-G1 ile |
| 3 | AI: özellik mühendisliği, modeller, Optuna, ensemble, kalibrasyon, belirsizlik, backtest | ✅ Motor tamamlandı ([rapor](04-faz3-raporu.md)); gerçek metrikler M-G1 verisiyle |
| 4 | Tahmin ve kupon: piyasa olasılıkları, otomatik kupon, birleşik olasılık, geçmiş | ⏭️ Sıradaki |
| 5 | Sanal simülasyon: sanal bakiye defteri, risk metrikleri, raporlar | ⏳ |
| 6 | SaaS: FREE/PRO/ELITE, abonelik, ödeme, lisans | ⏳ |
| 7 | Kullanıcı arayüzü: ana sayfa, dashboard, maç merkezi, AI analiz, kupon, mobil/PWA | ⏳ |
| 8 | 10 premium tasarım sistemi + Design Studio (önizleme, taslak, yayın, sürüm, geri alma) | ⏳ |
| 9 | Super Admin: Command Center, 30 modül, Data Explorer, Action Center, Ctrl+K | ⏳ |
| 10 | Son testler: E2E, güvenlik, performans, yedek/geri yükleme, CI/CD, dağıtım | ⏳ |

### Faz 1 — Teknik temel ✅
Çıktılar ve test sonuçları: [02-faz1-raporu.md](02-faz1-raporu.md).

### Faz 2 — Futbol verileri ✅ (altyapı)
Uygulanan: [03-faz2-raporu.md](03-faz2-raporu.md). Aşağıdaki plan metni kayıt için korunmuştur.

* `Provider` arayüzü (fikstür, sonuç, puan durumu, kadro, sakatlık, istatistik, oyuncu, xG) ve
  uyarlayıcılar. Her uyarlayıcı kayıtlı yanıtlarla (fixture dosyaları) test edilir.
* Şema: `countries, competitions, seasons, teams, venues, players, coaches, fixtures,
  fixture_events, fixture_team_stats, fixture_player_stats, lineups, injuries, suspensions,
  standings, provider_sync_runs, provider_quota`.
* Celery Beat programı veri türüne göre: canlı maç (kota izin verirse 15–60 sn), günün fikstürü
  (10 dk), kadro (maçtan 75 dk önce sıklaşır), tarihsel (gece).
* API kota bütçesi Redis'te; bütçe dolarsa düşük öncelikli işler ertelenir, canlı veri
  "bayat" olarak işaretlenir, **eski veri canlı gibi gösterilmez**.
* Veri kalitesi puanı: eksik alan oranı, tazelik, kaynaklar arası tutarlılık.

**Sağlayıcı değerlendirme ölçütleri (seçim M-G1'de, güncel fiyatlarla yapılacak):**

| Ölçüt | Sportmonks | API-Football | football-data.org |
|---|---|---|---|
| Kapsam | Çok geniş, xG eklentisi | Çok geniş, kadro/sakatlık var | Sınırlı lig seti (ücretsiz katman) |
| Tarihsel veri | Var | Var | Var (sınırlı) |
| Canlı veri | Var | Var | Ücretli katmanda |
| Ticari kullanım | Ücretli planlarla | Ücretli planlarla | Ücretsiz katman ticari kullanım için uygun değil |
| Not | xG ve tahmin özellikleri ayrı ücretli | Geliştirme için uygun başlangıç | Prototip/backtest için |

Fiyat ve kota rakamları burada bilinçli olarak yazılmadı: sağlayıcılar sık değiştiriyor; seçim
anında resmi sayfalardan doğrulanacak.

### Faz 3 — AI ✅ (motor)
Uygulanan: [04-faz3-raporu.md](04-faz3-raporu.md). Plan metni kayıt için korunmuştur.

* Özellik deposu (point-in-time): her özellik yalnızca maç başlangıcından **önceki** veriden
  hesaplanır; sızıntı testi zorunlu (gelecekteki bir maçın sonucunu değiştirmek geçmiş özellikleri
  değiştirmemeli).
* Temel modeller: Elo, Poisson, Dixon-Coles (zaman ağırlıklı), iki değişkenli Poisson; ardından
  GBM (LightGBM/XGBoost/CatBoost) — yalnızca kronolojik doğrulamada temel modeli geçerse üretime.
* Optuna: ~100 deneme, walk-forward bölme, budama, `seed=42`; son test dönemi optimizasyona hiç
  girmez. Deneyler ve parametreler model kayıt tablosunda (MLflow uyumlu) saklanır.
* Kalibrasyon (izotonik / Platt / sıcaklık), ECE, güvenilirlik diyagramı, Brier, log loss.
* Belirsizlik: bootstrap veya Bayesçi posterior; modeller arası uyum; çekimser kalma (abstention)
  kuralları ve gerekçeleri.
* Champion/Challenger, sürümleme, geri alma.

### Faz 4 — Tahmin ve kupon
* Skor dağılımı matrisinden tutarlı piyasalar (1X2, çifte şans, alt/üst, KG, doğru skor, İY
  piyasaları); ilişkili piyasalar aynı ortak dağılımdan türetilir.
* Kupon motoru: profil (düşük/dengeli/yüksek risk), maç sayısı, lig/piyasa filtresi. Aynı maçtan
  iki seçim ortak dağılımla, farklı maçlar Monte Carlo (10.000 → yakınsama kontrolü 50.000/100.000).
* Oran varsa (M-G2): marjdan arındırılmış olasılık, EV = p × oran − 1, CLV. Oran yoksa EV yok.
* Tahmin/kupon kaydı yayımlandığında dondurulur (tetikleyici), sonuç sonradan eklenir.

### Faz 5 — Sanal simülasyon
Çift kayıtlı sanal bakiye defteri (çekilemez, transfer edilemez), sabit tutar / yüzde / kesirli
Kelly, günlük risk ve işlem sınırı, drawdown, simüle ROI; kayıp kovalamayı teşvik eden hiçbir
özellik yok.

### Faz 6 — SaaS
Plan hakları (entitlements) tablosu, backend'de hak kontrolü, admin'den değiştirilebilir limitler;
`cloud/payments` uyarlayıcılarının abonelik modeline taşınması; webhook imzası ve idempotentlik;
lisans anahtarları (HMAC+pepper).

### Faz 7–8 — Arayüz ve 10 tasarım
Tasarım sistemi = token seti + yerleşim (layout) bileşenleri + bileşen varyantları. Her tasarımın
kendi `layouts/` ve kart/grafik varyantları vardır (yalnızca renk teması değil). Design Studio
tasarım yapılandırmasını sürümlü JSON olarak saklar (taslak → önizleme → onay → yayın → geri alma).

### Faz 9 — Super Admin
30 modül; Command Center metrikleri yalnızca gerçek kaynaktan, veri yoksa "veri yok" gösterir.
Kritik işlemlerde MFA + yeniden doğrulama + (gerekirse) ikinci yönetici onayı.

### Faz 10 — Yayın öncesi
Playwright E2E (masaüstü/tablet/telefon), axe erişilebilirlik, Lighthouse, yük testi, yedekten
geri yükleme tatbikatı, CI/CD, dağıtım belgesi.
