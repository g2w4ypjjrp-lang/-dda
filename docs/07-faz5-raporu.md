# Faz 5 Raporu — Sanal Portföy Simülasyonu

> Durum: **Tamamlandı (kod + testler).** Sanal birim (SB) gerçek para değildir; ödeme, çekim,
> yatırma veya transfer uç noktası **yoktur** (testle doğrulanır).

## 1. Tamamlanan işler

| Alan | Uygulama |
|---|---|
| Sanal hesap | Kullanıcı başına bir hesap; açarken "SB gerçek para değildir; çekilemez, transfer edilemez, satın alınamaz" onayı zorunlu. Başlangıç 10.000 SB |
| Değiştirilemez defter | Kayıt türleri sabit (açılış, tutar, ödeme, iade, sıfırlama). Yeni bakiyeyi **veritabanı tetikleyicisi** hesaplar ve hesaba yazar; bakiye negatife düşemez; defter güncellenemez/silinemez; hesap bakiyesi defter dışında değiştirilemez |
| Sanal bilet | Kullanıcının kendi, henüz başlamamış kuponuna bir bilet. İçerik değiştirilemez; sonuç bir kez yazılır |
| Oran kaynağı | **Model adil oranı** (1 / birleşik olasılık; piyasa oranı değildir, iyi kalibre modelde beklenen kâr sıfırdır) veya **kullanıcının girdiği oran** (doğrulanmamış; EV yalnızca bunda ve bu etiketle gösterilir). Lisanslı oran (M-G2) yok |
| Tutar yöntemleri | Sabit tutar, bakiyenin yüzdesi, kesirli Kelly (avantaj yoksa işlem önermez — "işlem yapmamak da bir karardır"). Tutar **sunucuda** hesaplanır |
| Risk sınırları | Tek bilet üst sınırı (% bakiye), günlük toplam risk (% gün başı bakiyesi), günlük bilet sayısı |
| Kayıp kovalamaya karşı | Riski artıran ayar değişiklikleri Türkiye saatiyle **ertesi gün** geçerli olur, azaltanlar hemen. "Kayıptan sonra katla" seçeneği yok. Sıfırlama 7 günde bir ve bekleyen bilet yokken; sıfırlama sayısı raporda görünür |
| Sonuçlandırma | Kupon sonuçlanınca aynı işlemde biletler: kazandı → tutar × oran; kaybetti → 0; geçersiz kupon veya geçersiz seçimli kazanan kupon → tutar iadesi |
| Rapor | Bakiye, simüle net ve ROI (yalnızca sonuçlanan biletler), kazanma oranı, ortalama oran, ortalama model olasılığı, en büyük düşüş (açık biletler dahil), oran kaynağına göre kırılım, bakiye zaman serisi, tarih filtresi; "Simüle edilmiş — gerçek para değildir" etiketi |
| Yönetim | `GET /admin/v1/virtual` (`virtual.read`): hesap sayısı, toplam sanal bakiye, bilet durumları, toplu simüle ROI |
| Denetim | Hesap açma, ayar değişikliği, sıfırlama denetim kaydına yazılır |

## 2. Yeni tablolar (geçiş 0005)

`virtual_accounts`, `virtual_ledger` (yalnızca ekleme, tetikleyiciyle bakiye zinciri),
`virtual_tickets` (içerik değiştirilemez).

## 3. API

`POST/GET /v1/virtual/account`, `PUT /v1/virtual/settings`, `POST/GET /v1/virtual/tickets`,
`GET /v1/virtual/report?from=&to=` (Türkiye günü), `POST /v1/virtual/reset`, `GET /admin/v1/virtual`.

## 4. Arayüz

* **Sanal Portföy** (`/sanal`, masaüstü menüde): açılış onayı, bakiye / net / simüle ROI / en büyük
  düşüş / bilet özeti, bakiye grafiği, tutar ve sınır ayarları (bekleyen ayar uyarısı), bilet geçmişi,
  sıfırlama, uyarı metni.
* **Kupon Merkezi:** kupon kaydedildikten sonra "Sanal bilet aç" — oran kaynağı seçimi ve açıklaması.

## 5. Test sonuçları

| Dosya | Test | Kapsam |
|---|---|---|
| api `test_virtual.py` | 10 | Tutar yöntemleri ve üst sınır, Kelly (avantajsızlıkta reddeder), adil oran, risk artışı tespiti, en büyük düşüş; hesap açma (onaysız reddedilir, ikinci hesap yok), bilet ve defter zinciri, kullanıcı oranında EV etiketi, defter/bakiye/bilet değiştirilemezliği, negatif bakiye reddi; günlük bilet ve risk sınırları, riski artıran ayarın ertesi gün uygulanması; kazanç/kayıp/iade sonuçlandırması, rapor (ROI, düşüş), sıfırlama kuralları; başkasının kuponu ve başlamış maç reddi; ödeme/çekim/transfer rotası olmadığı |
| web E2E `virtual.spec.ts` | 1 | Hesap aç (onay kutusu) → kupon oluştur/kaydet → sanal bilet → bakiye 9.900,00 SB → geçmişte "Bekliyor" |

**Toplam: API 148/148, ML 32/32, web E2E 8/8** (gerçek PostgreSQL 16 + Redis 7). `ruff`,
`mypy --strict`, `tsc` strict, `next build`: temiz.

## 6. Eksikler

| Konu | Durum |
|---|---|
| Lisanslı oranla simülasyon, CLV | **M-G2** |
| Sanal portföy için ayrı aylık/sezonluk rapor dışa aktarma (CSV) | Faz 9 raporlama |
| Plan bazlı sınırlar (FREE'de basit, ELITE'te gelişmiş simülasyon) | Faz 6 |
