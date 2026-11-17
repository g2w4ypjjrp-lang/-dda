# Faz 9 Raporu — Süper Yönetici Modülleri

> Durum: **Çekirdek tamamlandı (kod + testler).** Command Center, Action Center (sipariş inceleme
> akışıyla), Data Explorer, Ctrl+K komut paleti, Sistem Sağlığı + Log Merkezi, Güvenlik Merkezi,
> Özellik Bayrakları, Rol ve Yetki matrisi, Kupon Yönetimi ve Sanal Finans sayfaları çalışıyor.
> Spesifikasyondaki 30 modülün durumu aşağıdaki tabloda.

## 1. Modül durumu (30)

| # | Modül | Durum |
|---|---|---|
| 1 | Command Center | ✅ İşletme, kullanıcı, futbol, AI, kupon, sanal finans, sistem; yetkiye göre bölüm |
| 2 | Kullanıcı Yönetimi | ✅ Arama, filtre, detay, askı/aktifleştirme, etkinlik; abonelik/ödeme/kupon/sanal hesap bağlantıları |
| 3 | Abonelik Yönetimi | ✅ (Faz 6) |
| 4 | Finans Yönetimi | ✅ (Faz 6) + incelemedeki sipariş çözümü |
| 5 | Futbol Veri Merkezi | ✅ (Faz 2) |
| 6–8 | Maç / Lig / Takım Yönetimi | 🟡 Data Explorer'da görüntüleme ve ilişkili kayıtlar; elle düzenleme yok (veri sağlayıcıdan gelir, M-G1) |
| 9–11 | AI Intelligence / Model Lab / Optuna Lab | 🟡 Model Lab (Faz 3) + Command Center AI bölümü (kayma uyarısı, Optuna deneme sayısı); ayrı Optuna sayfası yok |
| 12 | Tahmin Yönetimi | 🟡 Data Explorer (tahminler); geri çekme işlemi yok (tahminler değiştirilemez) |
| 13 | Kupon Yönetimi | ✅ Özet, gerçekleşen/beklenen oran, son kuponlar, elle sonuçlandırma |
| 14 | Sanal Finans | ✅ Hesap, bakiye, bilet, simüle ROI |
| 15 | Design Studio | ✅ (Faz 8) |
| 16–18 | Website Control / İçerik / Bildirim | ⏳ Faz 7 kalanlarıyla (bildirim sistemi M-G6 e-posta sağlayıcısına bağlı) |
| 19 | API Yönetimi | ⏳ Dış API anahtarı ürünü yok; ilk sürümde gerekmiyor |
| 20 | Lisans Yönetimi | ✅ (Faz 6) |
| 21 | Sistem Ayarları | ✅ Salt okunur (gizli değerler hiç döndürülmez); değişiklik ortam değişkeniyle |
| 22 | Güvenlik Merkezi | ✅ Başarısız giriş/MFA, şüpheli IP, yönetici MFA, açık yönetici oturumları, güvenlik olayları |
| 23 | Log Merkezi | 🟡 Son 200 sunucu hatası (5xx) + yapılandırılmış JSON loglar stdout'ta; merkezi log toplama Faz 10 |
| 24 | Audit Log | ✅ (Faz 1) |
| 25 | Backup & Recovery | ⏳ Faz 10 (dağıtım altyapısıyla, M-G3) |
| 26 | Rol ve Yetki | ✅ Matris (7 rol × 35 izin, hassas izinler işaretli); atama Kullanıcılar'dan |
| 27 | Data Explorer | ✅ |
| 28 | System Health | ✅ |
| 29 | Feature Flags | ✅ Backend'de uygulanır |
| 30 | Admin Action Center | ✅ |

## 2. Command Center

`GET /admin/v1/overview`: bölümler yöneticinin okuma izinlerine göre gelir (ör. SUPPORT gelir
görmez). Değerler yalnızca gerçek kayıtlardan: günlük/aylık/toplam net gelir, MRR/ARR, ARPU, churn,
aktif/yeni/iptal abonelik; toplam/aktif (30 günde oturum açan)/yeni kullanıcı, FREE/PRO/ELITE,
askıdakiler; bugünkü/canlı/yaklaşan/ertelenen maç, aktif lig, son veri işi; şampiyon modeller,
30 günlük tahmin/çekimser, canlı Brier/log loss, Optuna deneme sayısı, **kayma uyarısı** (≥50
sonuçlanmış tahminde canlı log loss > test + 0.05); kupon ve sanal finans özetleri. Kayıt yoksa
"Veri yok". API/sunucu maliyeti bağlı olmadığı için açıkça "Veri yok" yazılır. Test ödemeleri gelire
katılmaz.

## 3. System Health ve Log Merkezi

* **İstek metrikleri:** her isteğin süresi ve durumu dakikalık kovalarda (Redis'te paylaşımlı,
  yoksa süreç içi). 5xx yanıtları son 200 kayıtlık halkada: zaman, yöntem, yol, durum, istek
  kimliği. **İstek gövdesi, sorgu parametresi ve kullanıcı bilgisi yazılmaz.**
* **Bileşenler:** PostgreSQL (gecikme + şema sürümü), Redis, kuyruk derinliği, işçi ve
  zamanlayıcı (yeni `mi.heartbeat` görevi: zamanlayıcı dakikada bir planlar, işçi çalıştırır; hiç
  alınmadıysa "Bilinmiyor", 5 dakikadan eskiyse "Çalışmıyor"), futbol API (son iş), ödeme API
  (yapılandırma), backend hata oranı ve yanıt süresi, API makinesinin CPU/RAM/disk değerleri.
* Ölçülemeyen değer uydurulmaz: "Bilinmiyor" / "Veri yok" ve nedeni yazılır.

## 4. Action Center

Uyarılar her istekte gerçek kayıtlardan hesaplanır ve yetkiye göre süzülür:

| Kategori | Kaynak |
|---|---|
| Kritik hatalar | Son 1 saatte 5xx |
| Ödeme sorunları | İncelemedeki sipariş (tutar uyuşmazlığı), 24 saatte imzası geçersiz bildirim |
| Veri güncelleme / API | Sağlayıcı yapılandırılmamış, 24 saatte başarısız veri işi |
| Model uyarıları | Şampiyon yok, kayma, günün tahminlerinin >%50'si çekimser |
| Başarısız görevler | İşçi/zamanlayıcı kalp atışı yok veya eski |
| Bekleyen işlemler | Açık tasarım taslağı, biten maçta 6 saattir sonuçlanmamış kupon seçimi |

"Görüldü" yalnızca o sorunun kimliğini gizler (ör. `sync_run:123`); aynı türden yeni sorun yeniden
görünür. **Sipariş inceleme akışı:** `finance.refund` (hassas, yeniden doğrulama) ile "Onayla ve
abonelik ver" veya sağlayıcı üzerinden "İade et"; karar notu zorunlu, denetim kaydına yazılır.

## 5. Data Explorer

* 13 beyaz listeli varlık (kullanıcılar, abonelikler, siparişler, ödeme olayları, lisanslar, ligler,
  takımlar, maçlar, tahminler, kuponlar, sanal hesaplar, sanal biletler, denetim kaydı). Yalnızca
  açıkça listelenen sütunlar okunur. **Parola özeti, MFA sırrı, belirteç, lisans özeti, ödeme ham
  verisi hiçbir zaman listelenmez** (testle doğrulanır).
* Her varlık `data.explore` + kendi okuma iznini ister. Arama aranabilir sütunlarda (LIKE
  kaçışlı), filtre tipine göre doğrulanmış eşitlik (enum/uuid/sayı/bool), sıralama yalnızca
  listelenen sütunlarda, sayfalama 100'e kadar.
* İlişkili kayıtlar: bağlantılı sütunlar (ör. siparişten kullanıcıya) ve ilişki düğmeleri
  (kullanıcının abonelikleri, ödemeleri, kuponları, etkinliği).
* Kayıtlı filtreler kişiye özel. **CSV** `data.export` (hassas) ister, en fazla 10.000 satır,
  formül enjeksiyonuna karşı temizlenir (`=`, `+`, `-`, `@` ile başlayan hücreler) ve filtreleriyle
  denetim kaydına yazılır.

## 6. Ctrl+K komut paleti

Yönetim panelinde Ctrl+K / Cmd+K: yetkili modüllere git; kayıt araması (e-posta, takım adı,
sipariş/maç/kupon numarası). Sonuçlar sunucuda yetkiye göre süzülür. Klavyeyle (↑ ↓ Enter Esc) kullanılır.

## 7. Özellik bayrakları

`registration_open`, `coupons_enabled`, `virtual_enabled`, `sales_enabled`, `maintenance_notice`.
Kapalı bayrak ilgili uçları **sunucuda** 503 `feature_disabled` ile durdurur (kayıt, kupon
oluşturma/önizleme/kaydetme, sanal hesap/bilet, satın alma). Özel mesaj verilebilir. Duyuru şeridi
mesaj ister ve sitenin üstünde gösterilir. Değişiklik `flags.manage` (hassas) ister ve denetim
kaydına yazılır.

## 8. Testler

| Dosya | Test | Kapsam |
|---|---|---|
| api `test_ops.py` | 5 | Overview bölümleri izne göre; kayıt yokken değerler `null`; sağlık bileşenleri (işçi kalp atışı yoksa "unknown"), metrik ve hata halkası (yalnızca güvenli alanlar); Action Center yetki süzgeci, görüldü işareti, sipariş inceleme onayı (ADMIN reddedilir, FINANCE_MANAGER onaylar, abonelik oluşur, tekrar 409); bayrakların kayıt ve kuponu durdurması, duyuru mesajı zorunluluğu; güvenlik merkezi sayımları; ayarlarda gizli değer olmaması; rol matrisi |
| api `test_explorer.py` | 2 | Beyaz listede hassas sütun yok; varlık yetkileri; arama, filtre, sıralama, sayfalama; geçersiz filtre/sıralama ve SQL meta karakterleri; ilişkili kayıt; kişiye özel kayıtlı filtre; CSV formül koruması ve denetim kaydı; global arama yetkisi |
| web E2E `admin.spec.ts` | 1 | Yönetici girişi → Command Center bölümleri → Ctrl+K ile kullanıcı bulma ve Action Center'a gitme → uyarıyı "görüldü" → Data Explorer araması + CSV indirme (denetim kaydı) → duyuru bayrağı açılınca sitede şerit → Sistem Sağlığı (PostgreSQL çalışıyor) → Güvenlik Merkezi → Rol matrisi |

**Toplam: API 181/181, ML 37/37, web E2E 13/13** (gerçek PostgreSQL 16 + Redis 7). `ruff`,
`mypy --strict`, `tsc` strict, `next build`: temiz.

## 9. Eksikler

| Konu | Durum |
|---|---|
| İkinci yönetici onayı (dört göz) | Henüz yok; kritik işlemler MFA + yeniden doğrulama + denetim kaydıyla korunuyor. İade/rol atama için Faz 10'da önerilir |
| Maliyet izleme (API ve sunucu) | Sağlayıcı faturası/izleme entegrasyonu yok → "Veri yok" |
| İşçi makinesi ve veritabanı sunucusu kaynakları | Yalnızca API makinesi ölçülüyor; harici izleme (Prometheus vb.) Faz 10 |
| Website Control, İçerik, Bildirim, API Yönetimi | Faz 7 kalanları / M-G6 |
| Backup & Recovery | Faz 10 (M-G3) |
| Merkezi log toplama ve arama | Faz 10 |
