# Ortak ayarlar ve yardımcılar (kur.ps1, calistir.ps1, futbol.ps1 tarafından yüklenir).
# Tüm yollar futbol klasörünün içindedir; sunucudaki başka hiçbir klasöre yazılmaz.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Proje   = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path      # ...\match-intelligence
$Kok     = Split-Path $Proje -Parent                                  # ...\Futbol
$Araclar = Join-Path $Kok 'araclar'
$Veri    = Join-Path $Kok 'veri'
$PgData  = Join-Path $Veri 'pgdata'
$Yedekler= Join-Path $Veri 'yedekler'
$Loglar  = Join-Path $Veri 'loglar'
$PidDir  = Join-Path $Veri 'pid'
$Ayarlar = Join-Path $Kok 'ayarlar'
$EnvDosya= Join-Path $Ayarlar 'futbol.env'
$WebDir  = Join-Path $Kok 'web'
$PgBin   = Join-Path $Araclar 'pgsql\bin'
$UvExe   = Join-Path $Araclar 'uv\uv.exe'
# Python doğrudan çalıştırılır (mi-api.exe başlatıcısı alt süreç açar; durdurma/öncelik için tek süreç).
$PyExe   = Join-Path $Proje 'api\.venv\Scripts\python.exe'
$MlPy    = Join-Path $Proje 'ml\.venv\Scripts\python.exe'      # tahmin motoru (ayrı ortam)

$Alan     = 'futbol.canarslan.net.tr'
$WebPort  = 3080          # önceden derlenmiş web paketi API'yi 127.0.0.1:8081'de bekler
$ApiPort  = 8081
$PgPort   = 5433
$PgServis = 'futbol-postgres'
$GorevYolu= '\Futbol\'

# Sabitlenmiş indirmeler (SHA-256 doğrulanır).
$PgUrl  = 'https://get.enterprisedb.com/postgresql/postgresql-16.11-1-windows-x64-binaries.zip'
$PgSha  = '3761aee1252a2083679020b5dc79c75df2d567eea708a2cbb9f6ff5402e27101'
$UvUrl  = 'https://github.com/astral-sh/uv/releases/download/0.9.5/uv-x86_64-pc-windows-msvc.zip'
$UvSha  = '515dc53d7553f1357d0abc1f70acd921fbb9e30230b1d9a08737236daa6ee920'

function Yaz([string]$m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Uyar([string]$m) { Write-Host "UYARI: $m" -ForegroundColor Yellow }
function Dur([string]$m) { Write-Host "HATA: $m" -ForegroundColor Red; exit 1 }

function Yonetici-mi {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ortam-Yukle {
    # futbol.env → bu sürecin ortam değişkenleri (ANAHTAR=DEĞER, # yorum).
    if (-not (Test-Path $EnvDosya)) { Dur "Ayar dosyası yok: $EnvDosya (önce kur.ps1)" }
    foreach ($satir in [IO.File]::ReadAllLines($EnvDosya)) {
        $s = $satir.Trim()
        if ($s -eq '' -or $s.StartsWith('#')) { continue }
        $i = $s.IndexOf('=')
        if ($i -lt 1) { continue }
        [Environment]::SetEnvironmentVariable($s.Substring(0, $i), $s.Substring($i + 1), 'Process')
    }
    $env:PATH = "$PgBin;$env:PATH"
}

function Mi-Admin {
    # mi-admin komutları (ortam yüklü olmalı): Mi-Admin migrate / backup / bootstrap ...
    & $PyExe -m mi_api.cli @args
}

function Sql-Dosya([string]$kullanici, [string]$parola, [string]$sql) {
    # Türkçe karakterler komut satırında bozulmasın diye SQL, UTF-8 dosyadan çalıştırılır.
    $f = Join-Path $env:TEMP ("futbol-" + [Guid]::NewGuid().ToString('N') + '.sql')
    [IO.File]::WriteAllText($f, $sql, (New-Object Text.UTF8Encoding($false)))
    $eskiEnc = $env:PGCLIENTENCODING; $env:PGCLIENTENCODING = 'UTF8'; $env:PGPASSWORD = $parola
    try { & (Join-Path $PgBin 'psql.exe') -h 127.0.0.1 -p $PgPort -U $kullanici -d futbol -v ON_ERROR_STOP=1 -q -f $f }
    finally { Remove-Item $f -Force -ErrorAction SilentlyContinue; Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue; $env:PGCLIENTENCODING = $eskiEnc }
}

function Uv-Ortam {
    # uv ve Python yalnızca futbol klasörünün içinde (araclar) tutulur.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Araclar 'python'
    $env:UV_CACHE_DIR = Join-Path $Araclar 'uv-onbellek'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
}

function Env-Ekle([string]$anahtar, [string]$deger) {
    # Ayar dosyasında anahtar yoksa ekler (varsa dokunmaz).
    if (-not (Select-String -Path $EnvDosya -Pattern "^$([regex]::Escape($anahtar))=" -Quiet)) {
        [IO.File]::AppendAllText($EnvDosya, "$anahtar=$deger`r`n", (New-Object Text.UTF8Encoding($false)))
    }
}

function Dusuk-Oncelikle([string]$exe, [string[]]$arg) {
    # Uzun işler (eğitim) botu yormasın: "normalin altı" öncelik, bitene kadar bekler.
    $p = Start-Process -FilePath $exe -ArgumentList $arg -WorkingDirectory $Kok -NoNewWindow -PassThru
    try { $p.PriorityClass = 'BelowNormal' } catch {}
    $p.WaitForExit()
    return $p.ExitCode
}

function Env-Deger([string]$anahtar) {
    foreach ($satir in [IO.File]::ReadAllLines($EnvDosya)) {
        if ($satir.StartsWith("$anahtar=")) { return $satir.Substring($anahtar.Length + 1) }
    }
    return $null
}

function Port-Dolu([int]$port) {
    [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

function Bos-Bellek-MB {
    [int](Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes
}

function Ag-Hizmeti-Adi {
    # "NT AUTHORITY\NETWORK SERVICE" Türkçe Windows'ta farklı adlandırılır: SID'den çözülür.
    (New-Object Security.Principal.SecurityIdentifier('S-1-5-20')).Translate([Security.Principal.NTAccount]).Value
}
