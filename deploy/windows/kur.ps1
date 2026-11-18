# futbol.canarslan.net.tr — Windows kurulumu (Docker'sız, tek sunucu modu).
# Yönetici PowerShell'de:  powershell -ExecutionPolicy Bypass -File C:\Kurulum\Futbol\match-intelligence\deploy\windows\kur.ps1
# Yalnızca C:\Kurulum\Futbol altına yazar; botunuza ve sitenize dokunmaz. Tekrar çalıştırmak güvenlidir.
param([switch]$BellekUyarisiniGec)
. (Join-Path $PSScriptRoot 'ortak.ps1')

if (-not (Yonetici-mi)) { Dur 'PowerShell''i "Yönetici olarak" açıp yeniden çalıştırın.' }
Yaz "Futbol klasörü: $Kok"

# --- 1. Ön kontroller -----------------------------------------------------------------------
$webPaket = Join-Path $Kok 'web-hazir'
if (-not (Test-Path (Join-Path $webPaket 'server.js')) -and -not (Test-Path (Join-Path $WebDir 'server.js'))) {
    Dur "Hazır web paketi yok: $webPaket (kurulum ZIP'indeki web-hazir klasörü)"
}
$bos = Bos-Bellek-MB
Yaz "Kullanılabilir bellek: $bos MB (futbol yaklaşık 350 MB kullanır)"
if ($bos -lt 700 -and -not $BellekUyarisiniGec) {
    Dur ("Bellek az ($bos MB). Botunuzu korumak için kurulum durduruldu. Sunucuda açık Claude/Chrome/ChatGPT " +
         "gibi programları kapatıp tekrar deneyin (ya da riski bilerek -BellekUyarisiniGec ekleyin).")
}
$disk = [int]((Get-PSDrive ($Kok.Substring(0, 1))).Free / 1GB)
if ($disk -lt 3) { Dur "Diskte en az 3 GB boş alan gerekli (şu an $disk GB)" }
$bizim = @()
foreach ($f in Get-ChildItem $PidDir -Filter *.pid -ErrorAction SilentlyContinue) { $bizim += [int](Get-Content $f.FullName) }
foreach ($port in @($WebPort, $ApiPort, $PgPort)) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
        $ad = (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        if (($bizim -notcontains $c.OwningProcess) -and $ad -notin @('postgres', 'node', 'python')) {
            Dur "Port $port başka bir program ($ad) tarafından kullanılıyor"
        }
    }
}
New-Item -ItemType Directory -Force -Path $Araclar, $Veri, $Yedekler, $Loglar, $PidDir, $Ayarlar | Out-Null

function Indir([string]$url, [string]$sha, [string]$hedef) {
    if ((Test-Path $hedef) -and ((Get-FileHash $hedef -Algorithm SHA256).Hash -eq $sha.ToUpper())) { return }
    Yaz "İndiriliyor: $url"
    Invoke-WebRequest -Uri $url -OutFile $hedef -UseBasicParsing
    $h = (Get-FileHash $hedef -Algorithm SHA256).Hash
    if ($h -ne $sha.ToUpper()) { Remove-Item $hedef -Force; Dur "Dosya doğrulanamadı (SHA-256 uyuşmuyor): $url" }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Zip-Ac([string]$zip, [string]$hedef, [string[]]$onekler, [int]$kirp) {
    $z = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($e in $z.Entries) {
            $ad = $e.FullName
            if (-not ($onekler | Where-Object { $ad.StartsWith($_) })) { continue }
            $parca = $ad.Split('/')
            $goreli = ($parca[$kirp..($parca.Length - 1)] -join '\')
            $yol = Join-Path $hedef $goreli
            if ($ad.EndsWith('/')) { New-Item -ItemType Directory -Force -Path $yol | Out-Null; continue }
            New-Item -ItemType Directory -Force -Path (Split-Path $yol) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $yol, $true)
        }
    } finally { $z.Dispose() }
}

# --- 2. Araçlar: uv (Python dahil) ve PostgreSQL 16 ------------------------------------------
$indir = Join-Path $Araclar 'indir'
New-Item -ItemType Directory -Force -Path $indir | Out-Null
if (-not (Test-Path $UvExe)) {
    $z = Join-Path $indir 'uv.zip'; Indir $UvUrl $UvSha $z
    Zip-Ac $z (Join-Path $Araclar 'uv') @('uv.exe') 0
}
if (-not (Test-Path (Join-Path $PgBin 'pg_ctl.exe'))) {
    $z = Join-Path $indir 'postgresql.zip'; Indir $PgUrl $PgSha $z
    Yaz 'PostgreSQL açılıyor (yalnızca bin, lib, share; pgAdmin atlanır)'
    Zip-Ac $z (Join-Path $Araclar 'pgsql') @('pgsql/bin/', 'pgsql/lib/', 'pgsql/share/') 1
    Remove-Item $z -Force
}

# --- 3. Ayar dosyası ve gizli değerler ---------------------------------------------------------
function Rastgele([int]$bayt) {
    $b = New-Object byte[] $bayt; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $b
}
function Parola { ([Convert]::ToBase64String((Rastgele 48)) -replace '[^A-Za-z0-9]', '').Substring(0, 32) }
if (-not (Test-Path $EnvDosya)) {
    Yaz 'Ayar dosyası ve gizli değerler oluşturuluyor'
    $dbParola = Parola; $suParola = Parola
    $satirlar = @(
        '# futbol.canarslan.net.tr ayarları — gizli değerler içerir, kimseyle paylaşmayın.',
        'MI_ENVIRONMENT=production',
        'MI_SINGLE_SERVER=true',
        'MI_DATABASE_PRIVATE_NETWORK=true',
        "MI_DATABASE_URL=postgresql://futbol:$dbParola@127.0.0.1:$PgPort/futbol",
        "FUTBOL_DB_PASSWORD=$dbParola",
        "FUTBOL_PG_SUPERUSER_PASSWORD=$suParola",
        ('MI_SECRET_KEK=' + [Convert]::ToBase64String((Rastgele 32))),
        ('MI_LICENSE_PEPPER=' + [Convert]::ToBase64String((Rastgele 32))),
        ('MI_METRICS_TOKEN=' + (Parola)),
        "MI_PUBLIC_WEB_URL=https://$Alan",
        "MI_PUBLIC_API_URL=https://$Alan",
        "MI_WEB_ORIGINS=[`"https://$Alan`"]",
        "MI_ADMIN_ORIGINS=[`"https://$Alan`"]",
        'MI_SESSION_COOKIE_SECURE=true',
        'MI_TRUSTED_PROXIES=["127.0.0.1"]',
        "MI_BACKUP_DIR=$Yedekler",
        'MI_BACKUP_KEEP=14',
        'MI_FOOTBALL_PROVIDER=none',
        'MI_FOOTBALL_API_KEY=',
        'MI_PAYMENT_PROVIDER=none',
        'MI_PAYMENTS_TEST_MODE=true',
        'MI_PAYMENTS_LIVE_ALLOWED=false',
        'MI_LOG_LEVEL=INFO',
        'MI_LOG_JSON=true'
    )
    [IO.File]::WriteAllLines($EnvDosya, $satirlar, (New-Object Text.UTF8Encoding($false)))
}
# Sonradan eklenen ayarlar (eski kurulumlarda eksikse eklenir; mevcut değerlere dokunulmaz).
Env-Ekle 'MI_FOOTBALL_LIVE_ENABLED' 'false'      # canlı skor yok: yalnızca fikstür, sonuç, puan durumu
Env-Ekle 'MI_FOOTBALL_DAILY_BUDGET' '2000'      # football-data.org ücretsiz: günlük sınır yok, dakikada 10
Env-Ekle 'MI_FOOTBALL_MINUTE_BUDGET' '8'
$ag = Ag-Hizmeti-Adi
# Ayar dosyasını yalnızca Yöneticiler, SYSTEM ve hizmet hesabı okuyabilir.
icacls $EnvDosya /inheritance:r /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F' '*S-1-5-20:R' | Out-Null

# --- 4. Klasör izinleri (hizmetler en düşük yetkili hesapla çalışır) ---------------------------
icacls $Araclar /grant '*S-1-5-20:(OI)(CI)RX' | Out-Null
icacls $Proje   /grant '*S-1-5-20:(OI)(CI)RX' | Out-Null
icacls $Veri    /grant '*S-1-5-20:(OI)(CI)M'  | Out-Null

# --- 5. PostgreSQL: veritabanı, yalnızca 127.0.0.1:5433, küçük bellek ayarları --------------
$suParola = Env-Deger 'FUTBOL_PG_SUPERUSER_PASSWORD'
$dbParola = Env-Deger 'FUTBOL_DB_PASSWORD'
if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) {
    Yaz 'Veritabanı oluşturuluyor'
    New-Item -ItemType Directory -Force -Path $PgData | Out-Null
    $pw = Join-Path $Ayarlar 'pw.tmp'
    [IO.File]::WriteAllText($pw, $suParola)
    try {
        & (Join-Path $PgBin 'initdb.exe') -D $PgData -U postgres --pwfile=$pw --auth=scram-sha-256 -E UTF8 --locale=C | Out-Host
        if ($LASTEXITCODE -ne 0) { Dur 'initdb başarısız' }
    } finally { Remove-Item $pw -Force -ErrorAction SilentlyContinue }
    $ek = @(
        '', '# --- futbol (kur.ps1): only 127.0.0.1, low memory ---',
        "listen_addresses = '127.0.0.1'", "port = $PgPort",
        'max_connections = 30', 'shared_buffers = 64MB', 'work_mem = 4MB',
        'maintenance_work_mem = 32MB', 'effective_cache_size = 256MB',
        'logging_collector = on', "log_directory = 'log'", 'log_rotation_size = 20MB', 'log_truncate_on_rotation = on'
    )
    Add-Content -Path (Join-Path $PgData 'postgresql.conf') -Value $ek -Encoding ASCII
    icacls $PgData /grant '*S-1-5-20:(OI)(CI)F' | Out-Null
}
if (-not (Get-Service $PgServis -ErrorAction SilentlyContinue)) {
    Yaz "Veritabanı hizmeti kaydediliyor ($PgServis, otomatik başlar)"
    & (Join-Path $PgBin 'pg_ctl.exe') register -N $PgServis -U 'NT AUTHORITY\NetworkService' -D $PgData -S auto -w | Out-Host
    if ($LASTEXITCODE -ne 0) { Dur 'Veritabanı hizmeti kaydedilemedi' }
}
if ((Get-Service $PgServis).Status -ne 'Running') { Start-Service $PgServis }
for ($i = 0; $i -lt 30; $i++) {
    & (Join-Path $PgBin 'pg_isready.exe') -h 127.0.0.1 -p $PgPort | Out-Null
    if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 1
}
if ($LASTEXITCODE -ne 0) { Dur "Veritabanı açılmadı; günlük: $PgData\log" }
$env:PGPASSWORD = $suParola
$psql = Join-Path $PgBin 'psql.exe'
$var = & $psql -h 127.0.0.1 -p $PgPort -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='futbol'"
if ($var -ne '1') {
    & $psql -h 127.0.0.1 -p $PgPort -U postgres -d postgres -v ON_ERROR_STOP=1 -qc "CREATE ROLE futbol LOGIN CREATEDB PASSWORD '$dbParola'" | Out-Host
    & $psql -h 127.0.0.1 -p $PgPort -U postgres -d postgres -v ON_ERROR_STOP=1 -qc "CREATE DATABASE futbol OWNER futbol ENCODING 'UTF8' TEMPLATE template0" | Out-Host
}
Remove-Item Env:PGPASSWORD

# --- 6. Python ortamı (bağımlılıklar hazır paketlerden; derleme yok) --------------------------
Yaz 'Python ve bağımlılıklar kuruluyor (ilk seferde birkaç dakika)'
Uv-Ortam
Push-Location (Join-Path $Proje 'api')
try {
    & $UvExe sync --locked --no-dev --python 3.12 | Out-Host
    if ($LASTEXITCODE -ne 0) { Dur 'Python bağımlılıkları kurulamadı' }
} finally { Pop-Location }
# Tahmin motoru daha önce kurulduysa (tahmin-hazirla) güncel koda göre yenilenir.
if (Test-Path $MlPy) {
    Push-Location (Join-Path $Proje 'ml')
    try { & $UvExe sync --locked --no-dev --python 3.12 | Out-Host } finally { Pop-Location }
}
& $UvExe cache clean | Out-Null   # disk tasarrufu

# --- 7. Veritabanı şeması --------------------------------------------------------------------
Ortam-Yukle
Mi-Admin migrate | Out-Host
if ($LASTEXITCODE -ne 0) { Dur 'Veritabanı geçişleri başarısız' }

# --- 8. Web paketi ---------------------------------------------------------------------------
if (Test-Path (Join-Path $webPaket 'server.js')) {
    Yaz 'Web paketi yerleştiriliyor'
    robocopy $webPaket $WebDir /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Dur 'Web paketi kopyalanamadı' }
    icacls $WebDir /grant '*S-1-5-20:(OI)(CI)RX' | Out-Null
    # Next.js yalnızca kendi önbelleğine yazar.
    $onbellek = Join-Path $WebDir '.next\cache'
    New-Item -ItemType Directory -Force -Path $onbellek | Out-Null
    icacls $onbellek /grant '*S-1-5-20:(OI)(CI)M' | Out-Null
}

# --- 9. Hizmet görevleri (açılışta başlar, çökerse yeniden başlar) -----------------------------
$calistir = Join-Path $PSScriptRoot 'calistir.ps1'
$kim = New-ScheduledTaskPrincipal -UserId $ag -LogonType ServiceAccount
$ayar = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
foreach ($h in @('api', 'web')) {
    $ad = "Futbol-$h"
    $is = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$calistir`" -Hizmet $h"
    Register-ScheduledTask -TaskPath $GorevYolu -TaskName $ad -Action $is -Principal $kim -Settings $ayar `
        -Trigger (New-ScheduledTaskTrigger -AtStartup) -Force | Out-Null
}
& (Join-Path $PSScriptRoot 'futbol.ps1') yeniden-baslat

# --- 10. İlk kurulum: kapalı önizleme ----------------------------------------------------------
$env:PGPASSWORD = $dbParola
$kayit = & $psql -h 127.0.0.1 -p $PgPort -U futbol -d futbol -tAc "SELECT count(*) FROM users"
Remove-Item Env:PGPASSWORD
if ($kayit -eq '0') {
    Sql-Dosya 'futbol' $dbParola "UPDATE feature_flags SET enabled = false, message = 'Site önizleme aşamasında; üye kaydı yakında açılacak.', updated_at = now() WHERE key = 'registration_open';"
    Yaz 'İlk kurulum: üye kaydı kapalı (önizleme). Yönetim → Özellik Bayrakları''ndan açılır.'
}

Write-Host ''
Yaz 'Kurulum tamam. Sıradaki adımlar (docs/windows-kurulum.md):'
Write-Host "  1) DNS: futbol → bu sunucunun IP'si (A kaydı)"
Write-Host "  2) Caddy: powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\caddy-ekle.ps1`""
Write-Host "  3) Tahminler (veri anahtarı futbol.env'e yazıldıktan sonra): futbol.ps1 tahmin-hazirla"
Write-Host "  4) Yönetici: powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\futbol.ps1`" yonetici eposta@adres `"Ad Soyad`""
