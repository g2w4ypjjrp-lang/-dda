# Faz 3 Raporu — AI Tahmin Motoru

> Durum: **Motor tamamlandı (kod + otomatik testler).** Gerçek model performansı **henüz yok ve
> raporlanmıyor**: gerçek maç verisi M-G1 (sağlayıcı anahtarı) ile gelecek. Bu fazdaki tüm sayısal
> sonuçlar, doğruluğu kanıtlamak için kullanılan **sentetik test verisine** aittir ve üründe
> gösterilmez.

## 1. Mimari

* Yeni paket [`ml/`](../ml/) (`mi_ml`): ağır kütüphaneler (numpy, scipy, scikit-learn, LightGBM,
  Optuna) API imajına girmez. Şema ve okuma API'si `api/` paketinde; ML paketi aynı veritabanına yazar.
* Ayrı Docker imajı (`ml/Dockerfile`) ve Celery `ml` kuyruğu işçisi; `docker compose --profile ml`.

## 2. Tamamlanan işler

| Alan | Uygulama |
|---|---|
| Skor matrisi ve piyasalar | 1X2, çifte şans, alt/üst (0.5–5.5), karşılıklı gol, toplam gol dağılımı, doğru skor, takım gol dağılımları — **hepsi tek ortak skor dağılımından**; ilişkili piyasalar birbiriyle tutarlı |
| Poisson ve Dixon-Coles | Hücum/savunma + ev sahibi avantajı, düşük skor düzeltmesi ρ, zaman sönümü ξ, L2 cezası, maksimum olabilirlik (L-BFGS-B); eğitim verisinde referans zamandan sonraki maç varsa reddeder |
| Elo | Ev sahibi avantajı ve gol farkı çarpanıyla; maç öncesi dereceler özellik olarak |
| Özellikler (sızıntısız) | Son 3/5/10/20 maç puan ve gol ortalamaları, ev/deplasman ayrımı, rakip gücüne göre düzeltilmiş form, xG ortalamaları (varsa), dinlenme günü, Elo. Bir maçın sonucu başlama saatinden 150 dk sonra "bilinir" sayılır; daha önceki maçların özellikleri onu göremez |
| Modeller | Elo+lojistik, Poisson, Dixon-Coles, lojistik regresyon (tüm özellikler), LightGBM |
| Optuna | TPE örnekleyici (`seed=42`), medyan budama, zaman sıralı genişleyen pencereli çapraz doğrulama; varsayılan 100 deneme; tüm denemeler kaydedilir |
| Değerlendirme | Ayarlama → doğrulama → test bölgeleri zaman sırasıyla ayrık. **Test dönemi hiçbir seçimde kullanılmaz.** Doğrulama ve test walk-forward: her pencere öncesi o ana kadar kesinleşmiş verilerle yeniden eğitim |
| Ensemble | Ağırlıklar doğrulama dönemindeki log loss'u en küçükleyecek şekilde öğrenilir (rastgele değil). Tekdüze tahminden kötü veya ağırlığı %2'nin altında kalan model **dışlanır**; nedeni kaydedilir |
| Kalibrasyon | Sıcaklık ölçekleme (doğrulama döneminde); sıralamayı değiştirmez |
| Metrikler | Brier, log loss, accuracy, precision/recall/F1 (makro), ECE, sınıf bazlı ECE, güvenilirlik diyagramı, karışıklık matrisi, örneklem sayısı; model başına + ensemble + sınıf frekansı tabanı |
| Model kayıt defteri | Sürüm, kapsam (lig), ayarlar, Optuna denemeleri, metrikler, özellik önemi, veri parmak izi (SHA-256), eğitim kesim zamanı. Model dosyası JSON + LightGBM metin biçimi (**pickle yok**). Kapsam başına tek şampiyon (veritabanı kısıtı) |
| Champion/Challenger | İlk sürüm şampiyon; sonrakiler aday. Şampiyon değişikliği ve geri alma yönetim panelinden (`models.manage` + yeniden doğrulama + denetim kaydı). Test metriği olmayan sürüm şampiyon yapılamaz |
| Tahminler | Maç başlamadan önce yazılmak zorunda (veritabanı kısıtı); **değiştirilemez ve silinemez** (tetikleyici). Tahmin anındaki özellikler, özellik özeti, model sürümü ve veri anlık görüntüsü saklanır. Aynı maç + sürüm + özellik için ikinci kayıt yazılmaz |
| Olasılık ≠ güvenilirlik | Ayrı alanlar: olasılıklar; güvenilirlik (test ECE + örneklem → yüksek/orta/düşük); veri kalitesi (geçmiş maç, xG kapsaması, ilk 11, tazelik); modeller arası uyum |
| Belirsizlik | Dixon-Coles bootstrap (varsayılan 30 yeniden eğitim) ile %10–%90 aralığı. **"Kapsama oranı test edilmiş güven aralığı değildir"** etiketiyle saklanır ve gösterilir |
| Çekimserlik | Yetersiz geçmiş, bilinmeyen takım, bayat veri, model anlaşmazlığı (>%20), geniş aralık (>%35), zayıf kalibrasyon (ECE >0.08), küçük test örneklemi (<100), başlamış maç → olasılık yayımlanmaz, nedenleri döner |
| Monte Carlo | Tohumlu simülasyon, 10k/50k/100k yakınsama denetimi; kupon ve sanal portföy (Faz 4–5) için hazır. Tek maç piyasaları kesin hesaplanır |
| Sonuçlandırma | Biten maçta 90' sonucu, Brier ve log loss bir kez yazılır (değiştirilemez) |
| Gerçekleşmiş performans | `GET /v1/predictions/performance` yalnızca sonuçlanmış, maçtan önce yayımlanmış tahminlerden hesaplanır; veri yoksa "veri yok" der, metrik uydurmaz |

## 3. Yeni tablolar (geçiş 0003)

`ml_model_versions`, `ml_tuning_trials`, `ml_predictions` (değiştirilemez),
`ml_prediction_outcomes` (değiştirilemez).

## 4. API uç noktaları

* `GET /v1/predictions?date=` — Türkiye gününe göre maç başına en son tahmin
* `GET /v1/predictions/fixtures/{id}` — en son tahmin, çekimserlik nedenleri, sonuç
* `GET /v1/predictions/performance?days=` — gerçekleşmiş performans
* `GET /admin/v1/models`, `GET /admin/v1/models/{id}` — `models.read` (Model Lab: metrikler, Optuna denemeleri, özellik önemi, aday–şampiyon farkı)
* `POST /admin/v1/models/{id}/promote` — `models.manage` + yeniden doğrulama

Her tahmin yanıtında: "Olasılıklar istatistiksel tahmindir; kesin sonuç veya kazanç garantisi
değildir. Bu platform gerçek bahis işlemi yapmaz."

## 5. Komutlar

```bash
mi-ml train   --competition-id <id> [--trials 100]   # eğit, kayda yaz (ilk sürüm şampiyon, sonrakiler aday)
mi-ml predict --competition-id <id> [--horizon-days 7] [--bootstrap 30]
mi-ml settle
```

Zamanlanmış tahmin ve sonuçlandırma: `MI_ML_SCHEDULE_ENABLED=true` + ML işçisi. Eğitim bilinçli
olarak zamanlanmaz.

## 6. Test sonuçları

| Paket | Dosya | Test | Kapsam |
|---|---|---|---|
| ml | `test_scores.py` | 8 | Piyasa tutarlılığı (4 senaryo), kapalı form Poisson eşitlikleri, ρ'nun beraberliğe etkisi, geçersiz girdi, simetri |
| ml | `test_models_math.py` | 9 | Dixon-Coles'un sentetik ligde gerçek parametreleri geri bulması (ev avantajı, μ, ρ, hücum gücü korelasyonu > 0.9), Poisson varyantı, sızıntı reddi, zaman sönümü, Elo, Monte Carlo yakınsama + tekrar üretilebilirlik, metrik bilinen değerleri, aşırı güvenin ECE ile yakalanıp sıcaklıkla düzeltilmesi, ensemble ağırlıkları |
| ml | `test_features.py` | 4 | Gelecek sonuçları değiştirmenin geçmiş özellikleri değiştirmemesi, 150 dk kuralı, yeni takımda NaN, değer aralıkları |
| ml | `test_backtest.py` | 5 | Dönemlerin zaman sırası ve ayrıklığı, Optuna kayıtları, ensemble/dışlama/metrikler, JSON gidiş-dönüşü (pickle'sız model aynı tahmini verir), parmak izi ve en az veri |
| ml | `test_pipeline_db.py` | 6 | Gerçek PostgreSQL: şampiyon/aday kaydı ve tek şampiyon kısıtı, tahmin yazımı, değiştirilemezlik, kopya önleme, gerekçeli çekimserlik, maçtan sonra tahmin yazılamaması, tek seferlik sonuçlandırma |
| api | `test_predictions_api.py` | 5 | En son tahmin, çekimser tahmin, Türkiye günü, gerçekleşmiş performansın yalnızca sonuçlanmışlardan hesaplanması, Model Lab yetkileri, yeniden doğrulama, şampiyon değiştirme ve geri alma, test edilmemiş sürüm reddi |

**Toplam: API 125/125, ML 32/32 geçti** (gerçek PostgreSQL 16 + Redis 7). `ruff`, `ruff format`,
`mypy --strict` iki pakette de hatasız. Bağımlılıklarda bilinen açık yok (`pip-audit`).

Sentetik test ligindeki bir eğitimde ortaya çıkan davranış (yalnızca mekanizma doğrulaması):
küçük örneklemde lojistik regresyon ve LightGBM doğrulamada tekdüze tahminden iyi olmadığı için
ensemble'a alınmadı; Poisson ve Dixon-Coles kaldı. Bu, "yalnızca gerçek katkı gösteren model üretime
girer" kuralının işlediğini gösterir. Gerçek veride hangi modellerin kalacağı veriyle belirlenecek.

## 7. Doğrulanamayanlar / eksikler

| Konu | Durum |
|---|---|
| Gerçek veride model performansı | **M-G1** (veri) bekliyor. Gerçek metrikler yalnızca gerçek veriyle, bu rapordaki yöntemle üretilecek |
| İlk yarı piyasaları | İlk yarı skor modeli gerekiyor (Faz 4 başında) |
| Bootstrap aralığının kapsama testi | Gerçek veriyle backtest'te ölçülecek; o zamana kadar "test edilmemiş" etiketi |
| Bayesçi hiyerarşik model, Glicko, iki değişkenli Poisson, CatBoost/XGBoost | Gerçek veride mevcut modellere katkı sağlayıp sağlamadığı ölçüldükten sonra (gereksiz model eklenmedi) |
| Sakatlık/kadro özellikleri | Faz 2 verisi var; geçmiş maçlar için kapsama gerçek veriyle ölçülüp eklenecek |
| Veri sapması (drift) uyarısı | Gerçek tahmin akışı başladığında, sonuçlanmış tahminlerin kayan log loss'u ile (Faz 9 Action Center) |
| SHAP | LightGBM özellik önemi (gain) kaydediliyor; SHAP açıklamaları arayüzle birlikte (Faz 7) |
| ML Docker imajı | Bu ortamda Docker daemon'ı yok; CI'da derleniyor |

## 8. Sıradaki adım — Faz 4: Tahmin ve kupon

İlk yarı modeli; kupon motoru (profil, maç sayısı, lig/piyasa filtreleri); aynı maçtaki seçimler
ortak skor dağılımından, farklı maçlar Monte Carlo ile birleşik olasılık; kupon geçmişi
(değiştirilemez); oran verisi olursa (M-G2) EV / CLV.

## Ek — Gerçek veriyle bulunan hata: Dixon-Coles ρ (2026-11)

İlk gerçek veriyle eğitimde (football-data.org, 9 lig) her lig **"rho bu gol beklentileriyle
geçersiz (negatif olasılık)"** hatasıyla durdu. Neden: Dixon-Coles düzeltmesi τ, yalnızca
`max(−1/λ, −1/μ) ≤ ρ ≤ min(1/(λμ), 1)` aralığında negatif olmaz. Ligin tek ρ'su güçlü–zayıf
eşleşmelerde (λ ≈ 5–7; ör. Şampiyonlar Ligi) bu aralığın dışına düşüyordu. Demo/sentetik veride
gol beklentileri dar olduğu için bu durum hiç oluşmamıştı.

Düzeltme (`scores.dc_rho`): ρ maç başına geçerli aralığa çekilir. τ en az 0,1 olur; yani düzeltme
bir skorun olasılığını en fazla %90 azaltır, hiçbir zaman sıfırlamaz. Eğitimdeki olabilirlik ve
tahmin aynı τ'yu kullanır. O maçta gerçekten uygulanan ρ, `ScoreMatrix.rho` alanına yazılır.
Olağan maçlarda (|ρ|·λ < 0,9) hiçbir şey değişmez.

Testler:
- `test_scores.py`: uç λ/μ/ρ birleşimlerinde olasılıklar geçerli kalıyor; olağan maçlarda ρ değişmiyor.
- `test_models_math.py::test_dixon_coles_handles_lopsided_matchups`: güçlü–zayıf ligde tüm eşleşmeler doğru çalışıyor.

Eski kod bu testte hatanın aynısını veriyor. Uç eşleşmeli sentetik ligde tam eğitim hattı (backtest,
LightGBM, ilk yarı) eski kodla aynı hatayla duruyor; yeni kodla tamamlanıyor. ML testleri: 45/45 geçti.
