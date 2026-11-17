# İlk Yarı Modeli ve "Kupona Ekle" Raporu

> Durum: **Tamamlandı (kod + testler).** İY piyasaları yalnızca İY modeli test döneminde kapıdan
> geçtiğinde yayımlanır. **Demo verisinde geçmedi** (aşağıda), bu yüzden demo ortamında maç sayfası
> İY olasılığı yerine nedenini gösterir. Eşik demo uğruna gevşetilmedi.

## 1. Yöntem

**Binom inceltme.** Bir takımın 90 dakikada attığı her gol, birbirinden bağımsız olarak `r`
olasılıkla ilk yarıda atılmış kabul edilir:

    P(İY = (a, b), MS = (i, j)) = M[i, j] · Binom(a; i, r_ev) · Binom(b; j, r_dep)

* `M` tahmin kaydındaki tam maç skor dağılımıdır (ensemble 1X2'sine uyarlanmış Dixon-Coles).
  Böylece İY olasılıkları tam maç tahminiyle **tutarlıdır**: MS marjinali değişmez, İY golü MS
  golünü aşamaz, İY/MS dokuz sonucunun İY ve MS marjinalleri yayımlanan 1X2'lerle aynıdır.
* `r` eğitim verisindeki İY gol payıdır (ev/deplasman ayrı, Beta(2,2) önselli en çok olabilirlik).
  İY skoru 90' skoruyla tutarsız maçlar (İY > MS) kullanılmaz.
* Piyasalar: İY 1X2, İY 0.5/1.5/2.5 alt-üst, İY karşılıklı gol, İY doğru skor, İY beklenen gol, **İY/MS**.

**Varsayım ve sınırı:** golün yarıya düşmesi skor durumundan bağımsız sayılır. Gerçek maçlarda oyun
durumu (öndeki takımın temkinli oynaması) bunu bozabilir. Bu yüzden model ölçülmeden yayımlanmaz.

## 2. Değerlendirme ve yayın kapısı

Ana modelle **aynı test döneminde**, 30 günlük pencerelerle, her pencere öncesi yalnızca o ana kadar
kesinleşmiş veriyle Dixon-Coles ve `r` yeniden eğitilir (örneklem dışı). Ölçülenler: İY 1X2 log
loss, Brier, ECE; İY/MS log loss. Karşılaştırma: **saf temel çizgi** (eğitim dönemindeki İY ve İY/MS
sonuç frekansları).

İY piyasaları ancak şu durumda yayımlanır: test örneklemi ≥ 100, eğitimde İY skoru kapsamı ≥ %80,
İY 1X2 ve İY/MS log loss temel çizgiden iyi, İY ECE ≤ 0.08. Aksi halde tahmin kaydına
`first_half: {available: false, reasons: [...]}` yazılır ve arayüz nedeni gösterir (çekimserlik).

Sonuç kayıt defterine yazılır (`ml_model_versions.metrics.first_half`), Model Lab'de görünür.

### Demo verisindeki sonuç (gerçek veri değildir)

| Ölçüt | İY modeli | Temel çizgi |
|---|---|---|
| Test örneklemi | 257 maç | — |
| İY 1X2 log loss | 1.025 | 1.060 |
| İY/MS log loss | 1.866 | 1.918 |
| İY ECE | **0.091** (eşik 0.08) | — |

Model temel çizgiden iyi ama kalibrasyon eşiğini geçmedi. Bu yüzden **yayımlanmadı**. Demo İY skorları
binom inceltmeyle üretildiği için demo, gerçek dünyada modelin doğruluğuna kanıt da sayılmaz. Gerçek
veriyle (M-G1) aynı kapı çalışacak. 257 maçta 10 kutulu ECE gürültülüdür. Eşiği ancak gerçek
veriyle ve daha büyük test örneklemiyle yeniden değerlendirmek doğru olur.

## 3. Kupon motoru

* Yeni seçimler: **İY 1/X/2**, **İY 0.5/1.5 Üst-Alt**, **İY/MS** (9 seçenek).
* Aynı maçta İY ve MS seçimleri (ör. "İY 1" + "2.5 Üst") aynı ortak dağılımdan **kesin**
  hesaplanır. API imajı saf Python kaldı: tahmin kaydındaki skor matrisi ve `r` ile hücreler
  binom olasılıklarıyla açılır. Monte Carlo doğrulaması bağımsız bir yol izler: her gol rastgele bir yarıya atanır.
* İY modeli yayımlanmamış maçta İY seçimi reddedilir (`market_unavailable`).
* Sonuçlandırma: İY seçimi İY skoruyla değerlendirilir. İY skoru gelmezse seçim beklemede kalır;
  maç 3 günden eskiyse ve hâlâ İY skoru yoksa seçim **geçersiz** sayılır.
* Performans: sonuçlandırmada İY skoru ve (yayımlanmışsa) İY Brier/log loss kaydedilir
  (geçiş 0007); "Model Şeffaflığı" sayfası İY log loss'u gösterir, veri yoksa "Veri yok".

## 4. "Kupona ekle"

* Maç sayfasında (PRO/ELITE) 1X2, çifte şans, alt/üst, KG ve İY seçimlerinin yanında **+** düğmesi.
  Seçimler tarayıcıda taslak olarak tutulur (sekmeler arası eşitlenir, en fazla 20).
* Kupon Merkezi → **Seçimlerim**: seçimler, `POST /v1/coupons/preview` ile sunucuda tahmin
  kayıtlarından **yeniden hesaplanan** birleşik olasılık ve Monte Carlo doğrulaması. Tarayıcıdaki
  etiket veya olasılığa güvenilmez. Kaydedince kupon değiştirilemez ve sanal bilet açılabilir.
* Eskiyen seçim (maç başladı, yeni tahmin yazıldı, İY yayımlanmadı) açık hata ile bildirilir.
* FREE pakette ekleme düğmesi gösterilmez; sunucu da önizlemeyi paket kontrolüyle reddeder.

## 5. Değişen / yeni

* ML: `mi_ml/halftime.py`, `data.py` (İY skoru), `pipeline.py` (değerlendirme, kayıt, sonuçlandırma),
  `predict.py` (`probabilities.first_half`).
* API: geçiş `0007_halftime` (`ml_prediction_outcomes`: `ht_home`, `ht_away`, `ht_brier`,
  `ht_log_loss`), kupon motoru İY piyasaları, `POST /v1/coupons/preview`, performans ve Model Lab'de İY.
* Web: maç analizinde İY bölümü (veya çekimserlik nedeni), **+** düğmeleri, Kupon Merkezi'nde
  Seçimlerim ve İY piyasa filtreleri, Model Şeffaflığı'nda İY log loss.

## 6. Testler

| Dosya | Yeni | Kapsam |
|---|---|---|
| ml `test_halftime.py` | 5 | Ortak dağılım MS marjinalini korur, İY ≤ MS; İY/MS marjinalleri = İY 1X2 ve MS 1X2; uç durumlar (r=0, r=1); `r`'nin sentetik veriden geri bulunması, eksik İY skoru; yayın kapısı (geçer / kapsam düşük / örneklem küçük); tahmin kaydı içeriği kapıya uyar |
| ml `test_pipeline_db.py` | güncellendi | Eğitimde İY değerlendirmesi kayda ve artefakta yazılır; küçük ligde yayımlanmaz ve nedeni yazılır; sonuçlandırmada İY skoru |
| api `test_coupon_engine.py` | 2 | Motorun binom hesabı **bağımsız türetmeyle** (iki ayrı yarı Poisson'u) aynı; İY + MS birleşik olasılığı ≠ çarpım; çelişen İY/MS seçimi 0; Monte Carlo uyumu; yayımlanmamış İY reddi |
| api `test_coupons_api.py` | 1 | FREE önizleme reddi ve İY verisinin gönderilmemesi; PRO önizleme (kaydetmez, birleşik > çarpım), yayımlanmamış İY reddi, İY kuponu kaydı, İY skoru gelene kadar bekleme, 3 gün sonra geçersiz |
| web E2E `basket.spec.ts` | 1 | Maç sayfası İY bölümü/nedeni → **+** ile iki seçim → Seçimlerim → birleşik olasılık + simülasyon → kaydet → geçmiş |

**Toplam: API 164/164, ML 37/37, web E2E 10/10** (gerçek PostgreSQL 16 + Redis 7). `ruff`,
`mypy --strict`, `tsc` strict, `next build`: temiz.

## 7. Eksikler

| Konu | Durum |
|---|---|
| İY modelinin gerçek veride doğrulanması | **M-G1** (veri sağlayıcı) |
| Skor durumuna bağlı (bağımsız olmayan) yarı modeli | Gerçek veride bağımsızlık testi kapıdan geçmezse sıradaki iyileştirme |
| İkinci yarı piyasaları, İY handikap | Gerekirse aynı ortak dağılımdan eklenebilir |
| Seçimlerim'in hesaplar arası saklanması | Şimdilik tarayıcıda; istenirse sunucu tarafı taslak |
