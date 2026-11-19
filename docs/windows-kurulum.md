# futbol.canarslan.net.tr — Windows VDS'ye kurulum (botunuzla aynı sunucu)

Sunucunuzda sanallaştırma kapalı olduğu için Docker kullanılamıyor. Bu kurulum, platformun
**Windows'a özel hafif sürümüdür**:
- Redis ve ayrı işçi süreçleri yoktur; zamanlanmış işler API'nin içinde çalışır.
- Toplam bellek kullanımı **~300–350 MB**'tır: API ~125 MB, web ~105 MB, veritabanı ~80–120 MB.

## Botunuz ve siteniz nasıl korunuyor

| Ne | Nasıl |
|---|---|
| Dosyalar | Her şey `C:\Kurulum\Futbol` altında. `C:\ATI` ve botunuzun klasörüne dosya yazılmaz. |
| Portlar | Futbol yalnızca sunucunun içinden dinler: web `127.0.0.1:3080`, API `127.0.0.1:8081`, veritabanı `127.0.0.1:5433`. Botunuzun kullandığı 3000/8000/8765 portlarına ve dışarıya hiçbir port açılmaz. |
| Yetki | Futbol hizmetleri en düşük yetkili sistem hesabıyla (**NetworkService**) çalışır; yönetici ya da SYSTEM yetkisi kullanmaz. |
| İşlemci | Futbol süreçleri **"normalin altı"** öncelikte çalışır; işlemci sıkışırsa botunuz önce gelir. |
| Bellek | Kurulum, kullanılabilir bellek **700 MB'ın altındaysa başlamaz**; botunuzu riske atmamak için. |
| Caddy | `C:\ATI\ayarlar\Caddyfile` dosyasına yalnızca işaretli **bir blok** eklenir. Önce dosyanın yedeği alınır; yeni ayar doğrulanmadan devreye girmez; sorun çıkarsa eski hâline döndürülür. Bu blok, sizin mevcut Caddyfile'ınızla birlikte gerçek Caddy 2.10'da doğrulandı. |
| Geri alma | `futbol.ps1 kaldir -Onay` ve `caddy-ekle.ps1 -Kaldir` komutları her şeyi kaldırır. |

## Doğrulama durumu

**Doğrulananlar:**
- Uygulama tarafı Linux'ta aynı ayarlarla, yani tek sunucu modunda, Redis olmadan ve aynı makinedeki veritabanıyla gerçekten çalıştırıldı. API açıldı ve zamanlanmış işler ilk turda başarıyla çalıştı.
- Web paketi, API'ye yönlendirmeyle birlikte çalıştı. Paket platformdan bağımsız: içinde yerel (işletim sistemine özel) modül yok.
- Python bağımlılıklarının hepsi Windows için hazır paket olarak bulunuyor; sunucuda derleme gerekmiyor.
- İndirilen dosyaların adresleri ve SHA-256 değerleri kontrol edildi.

**Doğrulanamayanlar:** PowerShell betikleri (`deploy/windows/*.ps1`) Windows'ta çalıştırılarak denenemedi. Bu yüzden kurulumu adım adım yapıyoruz; bir adım hata verirse durun ve çıktıyı gönderin.

## Adımlar

### 0. Belleği boşaltın

Kurulum sırasında ve sonrasında sunucuda açık **Claude, Chrome ve ChatGPT** uygulamalarını kapatın; bunlar ~1,3 GB kullanıyor. Kontrol için:

```powershell
(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes
```

Sonuç **700**'ün üstünde olmalı.

### 1. Kurulum paketini açın

`futbol-windows-kurulum.zip` dosyasını sunucuya kopyalayın. Sağ tıklayın → **Tümünü ayıkla** → hedef **`C:\Kurulum\Futbol`**. "Dosyaları değiştir" sorusuna **Evet** deyin.

Sonuçta şu iki klasör olmalı:
- `C:\Kurulum\Futbol\match-intelligence`
- `C:\Kurulum\Futbol\web-hazir`

### 2. DNS

Alan adı panelinizde `futbol` için bir **A kaydı** ekleyin. Değer olarak `canarslan.net.tr` ile aynı IP adresini yazın.

### 3. Kurulum

Başlat'a sağ tıklayın → **Terminal (Yönetici)** ya da **Windows PowerShell (Yönetici)**. Sonra:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Kurulum\Futbol\match-intelligence\deploy\windows\kur.ps1
```

İlk seferde 5–15 dakika sürer; yaklaşık 400 MB indirme yapar. Sırasıyla şunlar olur:
1. uv aracı ve Python 3.12 kurulur.
2. PostgreSQL 16 açılır; yalnızca gereken parçaları, ~120 MB.
3. Veritabanı ve hizmeti (`futbol-postgres`, otomatik başlar) oluşturulur.
4. Python bağımlılıkları kurulur ve veritabanı şeması hazırlanır.
5. Web paketi yerleştirilir.
6. Açılışta otomatik başlayan iki görev oluşturulur (`\Futbol\Futbol-api`, `\Futbol\Futbol-web`).
7. **Üye kaydı kapalı** önizleme modu açılır.

Gizli değerler (veritabanı parolaları, anahtarlar) otomatik üretilir. `C:\Kurulum\Futbol\ayarlar\futbol.env` dosyasına yazılır; bu dosyayı yalnızca yöneticiler ve hizmet hesabı okuyabilir. **Kimseyle paylaşmayın.**

### 4. Caddy'ye futbol adresini ekleyin

```powershell
powershell -ExecutionPolicy Bypass -File C:\Kurulum\Futbol\match-intelligence\deploy\windows\caddy-ekle.ps1
```

"Eklendi" görürseniz Caddy, DNS kaydı yayıldıktan sonra sertifikayı kendisi alır; birkaç dakika ile birkaç saat arasında sürebilir. Hata görürseniz hiçbir şey değişmemiştir; siteleriniz etkilenmez.

### 5. Yönetici hesabı

```powershell
powershell -ExecutionPolicy Bypass -File C:\Kurulum\Futbol\match-intelligence\deploy\windows\futbol.ps1 yonetici e-posta@adresiniz "Ad Soyad"
```

Bu komut tek kullanımlık bir bağlantı verir. Sonrasında:
1. Bağlantıyı açıp parolanızı belirleyin.
2. Hesabınızda iki adımlı doğrulamayı açın.
3. `https://futbol.canarslan.net.tr/yonetim/giris` adresinden yönetim paneline girin.

## Günlük kullanım

`futbol.ps1`'i Yönetici PowerShell'de çalıştırın:

| İş | Komut |
|---|---|
| Durum, bellek, son yedekler | `futbol.ps1 durum` |
| Elle yedek (geri yükleyerek doğrular) | `futbol.ps1 yedek` |
| Durdur / başlat / yeniden başlat | `futbol.ps1 durdur` · `baslat` · `yeniden-baslat` |
| Günlükler | `futbol.ps1 loglar api` · `futbol.ps1 loglar web` |
| Tamamen kaldır (veri korunur) | `futbol.ps1 kaldir -Onay` ve `caddy-ekle.ps1 -Kaldir` |
| Veriyle birlikte kaldır | `futbol.ps1 kaldir -Onay -VeriyiSil` |

* Yedekler her gün 03:17'de (UTC) otomatik alınır ve geçici bir veritabanına geri yüklenerek doğrulanır. Konumları: `C:\Kurulum\Futbol\veri\yedekler`.
* Sunucu arızasına karşı yedekleri ayrıca başka bir yere kopyalayın.
* Sunucu yeniden başladığında veritabanı hizmeti ve iki görev kendiliğinden açılır.

## Gerçek maç verisi ve tahminler (M-G1)

Veri sağlayıcı: **football-data.org, ücretsiz paket**. Kapsadığı ligler: Premier League, La Liga,
Serie A, Bundesliga, Ligue 1, Eredivisie, Primeira Liga, Championship, Şampiyonlar Ligi, Brezilya
Serie A, Dünya Kupası ve Avrupa Şampiyonası.

Bilmeniz gerekenler:
- **Süper Lig ücretsiz pakette yok.**
- Canlı skor takibi kapalıdır; yalnızca fikstür, sonuç ve puan durumu çekilir. Tahmin için bu yeterlidir.
- Ücretsiz paket ticari kullanım için değildir. Paket satışına (M-G5) geçmeden önce ücretli pakete geçin.

Adımlar:

1. https://www.football-data.org/client/register adresinden ücretsiz hesap açın ve e-postanıza gelen API anahtarını not edin. **Anahtarı kimseyle paylaşmayın.**
2. Yönetici PowerShell'de `notepad C:\Kurulum\Futbol\ayarlar\futbol.env` komutuyla ayar dosyasını açın. Şu iki satırı değiştirip kaydedin:
   ```
   MI_FOOTBALL_PROVIDER=football_data
   MI_FOOTBALL_API_KEY=<anahtarınız>
   ```
3. Sunucuda açık Claude, Chrome ve ChatGPT'yi kapatın; model eğitimi bellek ister. Sonra:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "C:\Kurulum\Futbol\match-intelligence\deploy\windows\futbol.ps1" tahmin-hazirla
   ```
   Bu komut sırasıyla şunları yapar:
   1. Tahmin motorunu kurar (~300 MB).
   2. Dün ile 8 gün sonrası arasındaki maçları çeker; ligler buradan oluşur.
   3. Her lig için son 4 sezonu yükler. Dakikada 10 istek sınırına uymak için istekler arasında beklenir; toplam 10–20 dakika sürer.
   4. Her lig için modeli düşük öncelikle eğitir.
   5. 30 dakikada bir çalışan **Futbol-tahmin** görevini kurar.

   Bir ligin ilk modeli kendiliğinden "şampiyon" olur ve tahminlerde kullanılır. Sonraki eğitimler aday olarak kaydedilir; şampiyon değişikliği Model Lab'dan yapılır.
4. Tahminler maçtan önce yazılır ve sonradan değiştirilemez. Model, verisi yetersiz kaldığı maçlarda tahmin vermez (çekimser kalır) ve nedenini gösterir; uydurma tahmin yayımlanmaz.

İzleme ve tekrar:
- Günlük: `futbol.ps1 loglar tahmin`
- Tahminleri hemen yeniden yazdırmak: `futbol.ps1 tahmin`
- Daha uzun geçmişle eğitmek (örneğin 6 sezon): `futbol.ps1 tahmin-hazirla -Sezon 6`

## Güncelleme (yeni paket geldiğinde)

1. Yeni `futbol-windows-kurulum.zip` dosyasını `C:\Kurulum\Futbol` içine açın ve "Dosyaları değiştir" sorusuna **Evet** deyin. Veri, ayarlar ve yedekler bu klasörlerin dışında olduğu için korunur.
2. Kurulumu yeniden çalıştırın: `kur.ps1`. Kurulum tekrar çalıştırmaya uygundur; kodu, bağımlılıkları ve veritabanı şemasını günceller, ardından hizmetleri yeniden başlatır.
   - Güncellemede bellek kontrolü, çalışan futbol süreçlerinin belleğini de hesaba katar; bu bellek, süreçler durdurulunca geri gelir.
   - Kurulum, dosyaları değiştirmeden önce futbol süreçlerini durdurur ve kapandıklarını doğrular. Bota ait süreçlere dokunmaz.
3. Model eğitimi daha önce hata verdiyse veri yüklü demektir. İndirmeyi atlayıp yalnızca eğitmek için: `futbol.ps1 tahmin-hazirla -SadeceEgit`.

## Ayar dosyası silindiyse (temiz kurulum)

`ayarlar\futbol.env` dosyasında veritabanı parolaları ve anahtarlar bulunur; yedeği yoktur.
- Önce Geri Dönüşüm Kutusu'na bakın. `ayarlar` klasörü oradaysa geri yükleyin.
- Geri Dönüşüm Kutusu'nda yoksa eski veritabanı açılamaz; temiz kurulum yapılır. Eski veri ve yedekler silinmez, `veri-eski` adıyla saklanır.

Yönetici PowerShell'de:

```powershell
Get-ScheduledTask -TaskPath '\Futbol\' -ErrorAction SilentlyContinue | Stop-ScheduledTask
Get-ChildItem C:\Kurulum\Futbol\veri\pid -Filter *.pid -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-Process -Id ([int](Get-Content $_.FullName)) -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -in @('node','python')) { Stop-Process -Id $p.Id -Force } }
Stop-Service futbol-postgres -ErrorAction SilentlyContinue
sc.exe delete futbol-postgres
Rename-Item C:\Kurulum\Futbol\veri veri-eski
Rename-Item C:\Kurulum\Futbol\araclar araclar-eski
```

Ardından:
1. ZIP'i yeniden açın.
2. `kur.ps1`'i çalıştırın.
3. `futbol.ps1 yonetici …` ile yönetici hesabını yeniden oluşturun.
4. Veri anahtarını `futbol.env` dosyasına yeniden yazın.
5. `futbol.ps1 tahmin-hazirla` komutunu çalıştırın.

Caddy ayarı `C:\ATI` altında olduğu için etkilenmez.

## Sonraki adımlar (onay kapıları)

Üye kaydını açmadan önce:
- **M-G4:** Yasal metinler.
- **M-G6:** E-posta gönderimi.

Gerçek maç verisi için **M-G1:** Veri sağlayıcı anahtarı `futbol.env` dosyasına yazılır, ardından `futbol.ps1 yeniden-baslat` çalıştırılır. Model eğitimi (ML), bu sunucunun belleği için ağırdır; o adımı ayrıca planlayacağız.

Ödeme (**M-G5**) en son açılır.
