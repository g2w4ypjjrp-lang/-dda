# futbol.canarslan.net.tr — mevcut VDS'ye ayrık kurulum

Bu kılavuz platformu **mevcut VDS'nize**, oradaki siteniz ve botunuzla **karışmadan** kurar.

## Ayrımın garantileri

| Ne | Nasıl ayrı tutulur |
|---|---|
| Dosyalar | Her şey tek klasörde: `/opt/futbol`. Başka hiçbir klasöre dosya yazılmaz. |
| Programlar | Ayrı bir Docker projesi (`futbol`): kapsayıcılar `futbol-…`, ağ ve veri birimleri `futbol_…`. Mevcut kapsayıcılarınıza dokunulmaz. |
| Veritabanı | Bu projeye özel PostgreSQL ve Redis kapsayıcıları; mevcut veritabanlarınız kullanılmaz. |
| Portlar | Dışarıya **hiçbir port açılmaz**. Uygulama yalnızca sunucunun içinden `127.0.0.1:3080` adresinde dinler. |
| Web sunucusu | Mevcut nginx/Apache ayarlarınız **değiştirilmez**; yalnızca `futbol.canarslan.net.tr` için **yeni, ayrı** bir dosya eklenir ve önce test edilir. |
| Kaynaklar | Bellek/işlemci üst sınırları (toplam en fazla ≈ 2,9 GB bellek; boşta ≈ 450 MB). Futbol sitesi yoğunlaşsa da botunuz yavaşlamaz. |
| Günlükler | Kapsayıcı başına en fazla 50 MB (döndürülür); disk dolmaz. |
| Geri alma | §8'deki komutlarla tamamen kaldırılır; sunucu kurulum öncesi hâline döner. |

Bu kurulum bir test ortamında baştan sona denendi:
- `futbol.sh kur` ile kurulum, sağlık kontrolleri, kayıtların kapalı gelmesi, yönetici oluşturma ve geri yükleme doğrulamalı yedek çalıştı.
- nginx 1.27 ve Apache 2.4 ayar dosyaları gerçek sunucu yazılımıyla test edildi. İstemci IP'sinin doğru iletildiği, sahte başlığın ezildiği ve `/metrics` ucunun dışarıya kapalı olduğu doğrulandı.

## 0. Ön kontrol (hiçbir şeyi değiştirmez)

Sunucuya bağlanın ve proje dosyalarını geçici bir yere koyun (ZIP'i yükleyip açabilirsiniz). Sonra:

```bash
bash deploy/vds/kontrol.sh
```

Çıktıyı bana gönderin. Bu çıktıdan şunlar anlaşılır: web sunucusunun türü (nginx, Apache ya da Plesk, cPanel gibi bir panel), boş bellek ve disk, Docker'ın kurulu olup olmadığı, 3080 portunun ve Docker alt ağının boş olup olmadığı. Sonraki adımlar buna göre netleşir.

## 1. DNS: tek bir kayıt

Alan adınızın DNS panelinde (alan adını aldığınız firma ya da Cloudflare) bir kayıt ekleyin:

| Tür | Ad | Değer |
|---|---|---|
| A | `futbol` | VDS'nizin IP adresi (`canarslan.net.tr` ile aynı IP olabilir) |

Mevcut kayıtlara dokunmayın. Cloudflare kullanıyorsanız ilk kurulumda turuncu bulutu **kapalı** (yalnızca DNS) tutun. Sertifika alındıktan sonra açabilirsiniz.

## 2. Docker (yoksa)

`kontrol.sh` "Docker kurulu değil" derse, resmi yöntemle kurun (Ubuntu/Debian):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

Docker zaten kuruluysa ve botunuz Docker'da çalışıyorsa bu adımı atlayın.

## 3. Kurulum

```bash
sudo mkdir -p /opt/futbol && sudo chown "$USER" /opt/futbol
# ZIP ile:   unzip match-intelligence-*.zip -d /tmp/mi && cp -a /tmp/mi/match-intelligence/. /opt/futbol/
# ya da git: git clone <depo adresi> /opt/futbol
cd /opt/futbol
sudo ./deploy/vds/futbol.sh kur
```

`kur` komutu sırasıyla şunları yapar:
1. `deploy/vds/.env` dosyasını oluşturur. Tüm parolaları ve anahtarları rastgele üretir; dosya izni 600 olur.
2. 3080 portunun ve `172.30.88.0/24` Docker alt ağının boş olduğunu denetler. Doluysa hiçbir şey yapmadan durur ve ne değiştirmeniz gerektiğini söyler.
3. İmajları derler (ilk seferde 5–10 dakika sürer) ve yığını başlatır.
4. İlk kurulumda **üye kaydını kapatır** (önizleme). Yasal metinler ve e-posta hazır olunca yönetim panelindeki **Özellik Bayrakları** sayfasından açılır.

## 4. Web sunucusu + HTTPS (yalnızca yeni bir dosya)

**nginx kullanıyorsanız:**

```bash
sudo cp deploy/vds/nginx/futbol.canarslan.net.tr.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/futbol.canarslan.net.tr.conf /etc/nginx/sites-enabled/
sudo nginx -t                  # "test is successful" görmeden devam etmeyin
sudo systemctl reload nginx    # reload: mevcut siteler kesintisiz devam eder
sudo certbot --nginx -d futbol.canarslan.net.tr
```

**Apache kullanıyorsanız:**

```bash
sudo a2enmod proxy proxy_http headers
sudo cp deploy/vds/apache/futbol.canarslan.net.tr.conf /etc/apache2/sites-available/
sudo a2ensite futbol.canarslan.net.tr
sudo apachectl configtest      # "Syntax OK" görmeden devam etmeyin
sudo systemctl reload apache2
sudo certbot --apache -d futbol.canarslan.net.tr
```

* Sunucunuzda `/etc/nginx/sites-enabled` dizini yoksa dosyayı `/etc/nginx/conf.d/` altına kopyalayın.
* `nginx -t` ya da `configtest` hata verirse `reload` yapmayın. Eklediğiniz dosyayı silmeniz yeterli; mevcut siteleriniz hiç etkilenmemiş olur.
* `certbot` kurulu değilse: `sudo apt install certbot python3-certbot-nginx`. Apache için paket adı `python3-certbot-apache`.
* **Plesk, cPanel, aaPanel ya da CyberPanel kullanıyorsanız** dosya kopyalamayın. Panelde `futbol.canarslan.net.tr` alt alanını oluşturun, "Reverse Proxy / Proxy" ayarına `http://127.0.0.1:3080` yazın ve panelin Let's Encrypt düğmesiyle sertifika alın. `kontrol.sh` çıktısını gönderirseniz panele özel adımları yazarım.
* Site **yalnızca HTTPS ile tam çalışır**: giriş çerezleri yalnızca güvenli bağlantıda gönderilir.

## 5. Yönetici hesabı

```bash
sudo ./deploy/vds/futbol.sh yonetici eposta@adresiniz "Ad Soyad"
```

Bu komut tek kullanımlık, 24 saat geçerli bir bağlantı verir. Sonrasında:
1. Bağlantıyı açıp parolanızı belirleyin.
2. Hesabım bölümünden iki adımlı doğrulamayı açın.
3. `https://futbol.canarslan.net.tr/yonetim/giris` adresinden yönetim paneline girin.

## 6. Günlük işler

| İş | Komut |
|---|---|
| Durum, son yedekler, şema sürümü | `sudo ./deploy/vds/futbol.sh durum` |
| Elle yedek (geri yükleyerek doğrular) | `sudo ./deploy/vds/futbol.sh yedek` |
| Güncelleme (önce yedek alır) | `sudo ./deploy/vds/futbol.sh guncelle` |
| Günlükler | `sudo ./deploy/vds/futbol.sh loglar api` |
| Durdurma (veri korunur) | `sudo ./deploy/vds/futbol.sh durdur` |

Yedekler her gün 03:17'de (UTC) otomatik alınır ve doğrulanır; son 14 yedek tutulur. Sunucu
arızasına karşı yedekleri **sunucu dışına** da kopyalayın. Yedeklerin yeri:
`docker volume inspect futbol_backups -f '{{.Mountpoint}}'`.

## 7. Sonraki adımlar (onay kapıları)

Kayıtları açmadan önce:
- **M-G4:** Yasal metinler (KVKK, gizlilik, koşullar). Yönetim → İçerik sayfasından yayımlanır.
- **M-G6:** E-posta sağlayıcısı. Doğrulama ve parola sıfırlama e-postaları buna bağlı.

Gerçek içerik için:
- **M-G1:** Futbol veri sağlayıcısının anahtarı `deploy/vds/.env` dosyasına (`MI_FOOTBALL_PROVIDER`, `MI_FOOTBALL_API_KEY`) yazılır, ardından `futbol.sh kur` çalıştırılır. Model eğitimi için ML işçisi açılır (`--profile ml`).

Ödeme (**M-G5**) en son açılır.

## 8. Tamamen kaldırma (geri alma)

```bash
cd /opt/futbol
docker compose -p futbol -f deploy/vds/docker-compose.yml --env-file deploy/vds/.env down       # kapsayıcı + ağ (veri kalır)
docker compose -p futbol -f deploy/vds/docker-compose.yml --env-file deploy/vds/.env down -v    # VERİ DE SİLİNİR
sudo rm /etc/nginx/sites-enabled/futbol.canarslan.net.tr.conf /etc/nginx/sites-available/futbol.canarslan.net.tr.conf
sudo nginx -t && sudo systemctl reload nginx
sudo rm -rf /opt/futbol
```

Bu komutlar yalnızca `futbol` adlı projeyi ve `futbol.canarslan.net.tr` dosyasını siler. Diğer siteleriniz ve botunuz etkilenmez.
