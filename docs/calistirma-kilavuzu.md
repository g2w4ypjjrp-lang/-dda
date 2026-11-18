# Çalıştırma kılavuzu (üretim)

> **Seçilen dağıtım (M-G3):** `futbol.canarslan.net.tr`, mevcut VDS'de diğer site ve botlardan ayrık
> kurulum → **[docs/vds-kurulum.md](vds-kurulum.md)**. Bu dosya, ayrı bir sunucu ve yönetilen
> veritabanıyla kurulum (docker-compose.prod.yml + Caddy) içindir.

Bu kılavuz, **M-G3 (dağıtım / alan adı) onayından sonra** platformu üretimde çalıştırmak içindir.
Onay verilmeden hiçbir sunucuya dağıtım yapılmaz. Diğer onay kapıları (M-G1 veri sağlayıcı, M-G2 oran
verisi, M-G4 hukuk metinleri, M-G5 canlı ödeme, M-G6 e-posta) ayrı ayrı açılır; kapalı olan özellik
arayüzde "veri yok / kapalı" olarak görünür, uydurma veri gösterilmez.

## 1. Mimari

```
İnternet ──443──▶ Caddy (TLS, HSTS, /metrics kapalı)
                    └─▶ web:3000 (Next.js; /v1 ve /admin/v1'i API'ye vekil eder)
                           └─▶ api:8080 (FastAPI) ──▶ yönetilen PostgreSQL 16 (TLS, verify-full)
                                                   └─▶ yönetilen Redis 7 (TLS)
                  worker (Celery: veri işleri, kupon sonuçlandırma, bildirim taraması, günlük yedek)
                  beat   (zamanlayıcı)      ml-worker (isteğe bağlı, --profile ml)
                  prometheus (isteğe bağlı, --profile monitoring; api:8080/metrics jetonla)
```

* Tüm kapsayıcılar root olmayan kullanıcıyla, salt okunur kök dosya sistemiyle, `no-new-privileges`
  ve tüm Linux yetenekleri düşürülmüş olarak çalışır.
* API, `X-Forwarded-For` başlığına yalnızca web kapsayıcısının sabit adresinden (`172.30.10.3`)
  geldiğinde güvenir (`MI_TRUSTED_PROXIES`); hız sınırları ve denetim kaydı gerçek istemci IP'sini görür.
* Uygulama üretim ortamında güvensiz ayarla **açılmaz**: HTTPS olmayan köken, `sslmode=verify-full`
  olmayan veritabanı adresi, Redis'siz çalışma, eksik `MI_SECRET_KEK` veya ödeme simülatörü reddedilir.

## 2. Ön koşullar

| Gereksinim | Not |
|---|---|
| Linux sunucu, Docker Engine 24+ ve Compose v2 | 2 vCPU / 4 GB RAM başlangıç için yeterli (yerel ölçüm: tek API süreci ~370 istek/sn) |
| Alan adı + DNS A/AAAA kaydı | `MI_DOMAIN` ve `www.` alt alanı sunucuyu göstermeli; 80 ve 443 açık |
| Yönetilen PostgreSQL 16 | TLS zorunlu; sağlayıcının CA sertifikası `deploy/secrets/pg-ca.pem` |
| Yönetilen Redis 7 | `rediss://` (TLS) |
| Gizli bilgi deposu | `.env.prod` buradan üretilir; git'e girmez |
| Yedek için ikinci konum | `backups` birimi başka disk/bölgeye eşitlenmeli (ör. nesne depolama, şifreli) |

## 3. İlk kurulum

```bash
git clone <depo> && cd match-intelligence
cp .env.prod.example .env.prod          # değerleri gizli bilgi deposundan doldurun
mkdir -p deploy/secrets && cp <sağlayıcı-ca>.pem deploy/secrets/pg-ca.pem && chmod 0444 deploy/secrets/pg-ca.pem

# Anahtarlar (her biri ayrı): MI_SECRET_KEK, MI_LICENSE_PEPPER, MI_METRICS_TOKEN
python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"

docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml --env-file .env.prod ps         # api "healthy" olmalı

# İlk süper yönetici (varsayılan parola yoktur; tek kullanımlık bağlantı ekrana yazılır)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api \
  mi-admin bootstrap --email yonetici@alanadi --name "Ad Soyad"
```

Bağlantıyla parola belirlenir → hesapta iki adımlı doğrulama açılır → `/yonetim/giris`.

**İlk gün denetim listesi**

1. `https://ALAN_ADI` açılıyor, sertifika geçerli; `https://ALAN_ADI/metrics` → 404.
2. Yönetim → Sistem Sağlığı: veritabanı/Redis/işçi/zamanlayıcı "ok"; şema sürümü = en son geçiş.
3. Yönetim → Action Center: kritik uyarı yok (veri sağlayıcı M-G1 bekliyorsa bu bilgi olarak görünür).
4. İkinci bir yönetici atanır; ardından **Özellik Bayrakları → dual_control** açılır (iade, sipariş
   kararı ve rol atama ikinci yöneticinin onayını ister; kuralı kapatmak da onay ister).
5. `mi-admin backup` elle bir kez çalıştırılır ve Yönetim → Yedekler'de "Geri yüklendi, sağlam" görülür.

## 4. Güncelleme (yeni sürüm)

```bash
git fetch && git checkout <etiket>
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm worker mi-admin backup   # önce yedek
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d    # migrate hizmeti önce çalışır
```

* Geçişler ileri yönlüdür ve elle yazılmış SQL'dir; her geçiş tek işlemde uygulanır (yarım kalmaz).
* Büyük tablolarda yeni indeks gerekirse bakım penceresinde `CREATE INDEX CONCURRENTLY` ile önceden
  oluşturulabilir; geçişteki aynı adlı indeks o zaman `IF NOT EXISTS` olacak şekilde düzenlenmelidir.
* **Geri dönüş:** bir önceki etikete dönüp imajı yeniden derleyin. Şema geriye uyumsuz değiştiyse
  (raporlarda belirtilir) veritabanı da güncelleme öncesi yedekten geri yüklenir (§6).

## 5. Yedekleme

* İşçi her gün **03:17 UTC**'de `pg_dump --format=custom` ile `/backups` altına yedek alır; dosya önce
  `.part` adıyla yazılır, bitince yeniden adlandırılır, SHA-256 özeti `.sha256` yan dosyasına ve
  `backups` tablosuna yazılır. Son `MI_BACKUP_KEEP` (varsayılan 14) başarılı yedek tutulur.
* Her yedekten hemen sonra **gerçek geri yükleme denemesi** yapılır: yedek geçici bir veritabanına
  yüklenir; şema sürümü, tablo sayısı, temel satır sayıları ve denetim kaydı hash zinciri denetlenir;
  geçici veritabanı silinir. Bunun için veritabanı kullanıcısının `CREATEDB` yetkisi olmalıdır; yoksa
  sonuç "geri yükleme denenmedi" der ve yedek **doğrulanmış sayılmaz** (Action Center uyarır).
* Uyarılar: yedek alınamazsa, 26 saattir başarılı yedek yoksa veya doğrulama başarısızsa Action
  Center'da kritik uyarı ve Prometheus'ta `MiBackup*` uyarıları.
* `/backups` birimi sunucu dışına eşitlenmelidir (ör. günlük şifreli kopya). Sunucu kaybında yerel
  birim de kaybolur.

## 6. Yedekten geri dönüş

```bash
# 1) Yazmayı durdurun (kullanıcılar bakım duyurusunu görsün: Bayraklar → maintenance_notice)
docker compose -f docker-compose.prod.yml --env-file .env.prod stop web worker beat api

# 2) Önce ayrı bir veritabanına geri yükleyip kontrol edin (önerilen)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm worker \
  mi-admin restore /backups/mi-YYYYmmddTHHMMSSZ-xxxxxx.dump --target-url "postgresql://.../mi_geri?sslmode=verify-full&sslrootcert=/etc/mi/pg-ca.pem" --yes

# 3) Çalışan veritabanının üzerine (yalnızca hizmetler durmuşken)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm worker \
  mi-admin restore /backups/<dosya>.dump --target-url "$MI_DATABASE_URL" --yes --overwrite-current

# 4) Şema ve zincir denetimi, sonra hizmetleri açın
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api mi-admin migrate
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api mi-admin audit-verify
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

`restore` önce SHA-256 özetini doğrular (tutmazsa hiçbir şey yapmaz), tek işlemde yükler (hata olursa
geri alınır) ve hedef çalışan veritabanıysa `--overwrite-current` olmadan reddeder.

**Tatbikat:** ayda bir kez 2. adımı ayrı bir veritabanında uygulayın ve süreyi kaydedin.

## 7. İzleme ve uyarılar

* `GET /metrics` (Prometheus metin biçimi) yalnızca `MI_METRICS_TOKEN` ayarlıysa açıktır ve
  `Authorization: Bearer` ister; Caddy bu yolu dışarıya 404 döner. Ölçüler gerçek kaynaklardan anlık
  hesaplanır; bilinmeyen değer yazılmaz (ör. hiç kalp atışı yoksa yaş ölçüsü yoktur).
* Örnek yapılandırma: `deploy/prometheus/prometheus.yml`, kurallar `deploy/prometheus/alerts.yml`
  (`promtool check rules` ile doğrulandı). Jeton dosyası: `deploy/prometheus/mi_metrics_token` (0400).
* Uyarılar: API okunamıyor, bileşen sağlıksız, 5xx artışı, yavaş yanıt, işçi kalp atışı eski/yok, kuyruk
  birikmesi, yedek yok/eski/doğrulanamadı, 12 saattir bekleyen dört göz talebi.
* Uygulama günlükleri JSON'dur (`MI_LOG_JSON=true`), her satırda istek kimliği vardır; yanıt başlığı
  `X-Request-ID` ile kullanıcı bildirimi günlüklerle eşleştirilir. Merkezi günlük toplayıcı (Loki,
  ELK, bulut sağlayıcının hizmeti) Docker günlük sürücüsüyle bağlanır.
* Yönetim panelinde aynı bilgiler: Sistem Sağlığı, Action Center, Güvenlik Merkezi, Yedekler.

## 8. Olay müdahalesi

| Durum | İlk adım |
|---|---|
| Site açılmıyor | `docker compose ... ps`; Caddy günlüğü (sertifika/DNS); `api` sağlık durumu |
| 5xx artışı | Sistem Sağlığı → son hatalar (istek kimliği) → API günlüğünde aynı kimlik |
| İşçi kalp atışı yok | `worker`/`beat` günlükleri; Redis bağlantısı; yeniden başlatma |
| Şüpheli giriş / hesap ele geçirme | Kullanıcıyı askıya alın (oturumlar kapanır); Güvenlik Merkezi; denetim kaydı |
| Ödeme bildirimi imzası geçersiz | Action Center; sağlayıcı panelinde anahtar; `MI_PAYTR_*`/`MI_IYZICO_*` |
| Özelliği acilen durdurma | Özellik Bayrakları (kayıt, kupon, sanal portföy, satış); duyuru şeridi |
| Veri bozulması | Yazmayı durdurun → §6 geri dönüş → `mi-admin audit-verify` |

Denetim kaydı hash zincirlidir: `mi-admin audit-verify` (veya Yönetim → Denetim Kaydı → Doğrula)
zincirin kırıldığı ilk kaydı gösterir.

## 9. Anahtar yönetimi

* `MI_SECRET_KEK` kullanıcı ve yöneticilerin MFA sırlarını şifreler; kaybolursa MFA'lar yeniden
  kurulmalıdır. **Döndürme** (yılda bir veya sızıntı şüphesinde), bakım penceresinde:

  ```bash
  docker compose -f docker-compose.prod.yml --env-file .env.prod stop api worker beat web
  export MI_NEW_SECRET_KEK="$(python3 -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())')"
  docker compose ... run --rm -e MI_NEW_SECRET_KEK api mi-admin rotate-kek --dry-run   # yalnızca denetim
  docker compose ... run --rm -e MI_NEW_SECRET_KEK api mi-admin rotate-kek
  # .env.prod: MI_SECRET_KEK=<yeni değer>  (gizli bilgi deposunda da güncelleyin)
  docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
  ```

  Tüm sırlar tek işlemde taşınır; tek bir sır bile çözülemezse hiçbir şey değişmez. Tekrar
  çalıştırmak güvenlidir (taşınmış sırlar atlanır). Yeni anahtarı yüklemeyen bir süreç MFA
  girişinde 500 değil "şu anda yapılamıyor" (503) döner ve günlüğe anahtar uyuşmazlığı yazar.
* `MI_LICENSE_PEPPER` değişirse üretilmiş lisans anahtarları geçersizleşir.
* `MI_METRICS_TOKEN` istendiği zaman değiştirilebilir (Prometheus jeton dosyasıyla birlikte).
* Ödeme sağlayıcı anahtarları yalnızca sağlayıcı panelinde yenilenir; canlı mod M-G5 onayı ister.

## 10. Onay kapıları kontrol listesi

| Kapı | Açılınca yapılacak |
|---|---|
| M-G1 veri sağlayıcı | `MI_FOOTBALL_PROVIDER` + anahtar; Futbol Veri Merkezi'nden tarihsel yükleme; model eğitimi |
| M-G2 oran verisi | (henüz entegrasyon yok) EV gösterimi yalnızca bu onaydan sonra |
| M-G3 dağıtım | Bu kılavuz |
| M-G4 hukuk | Yönetim → İçerik: KVKK, gizlilik, kullanım koşulları, çerez, mesafeli satış metinleri yayımlanır |
| M-G5 canlı ödeme | `MI_PAYMENTS_LIVE_ALLOWED=true`, `MI_PAYMENTS_TEST_MODE=false`; önce küçük tutarlı gerçek işlem |
| M-G6 e-posta | E-posta sağlayıcısı entegrasyonu (şu an e-postalar `email_outbox` tablosunda bekler) |
