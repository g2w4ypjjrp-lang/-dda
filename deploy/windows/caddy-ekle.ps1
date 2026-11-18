# Mevcut Caddy'ye futbol.canarslan.net.tr bloğunu ekler (ya da -Kaldir ile çıkarır).
# Güvenlik: önce Caddyfile'ın yedeği alınır; yeni ayar doğrulanmadan devreye girmez; yeniden
# yükleme başarısız olursa eski dosya geri konup yeniden yüklenir. Diğer bloklara dokunulmaz.
param(
    [string]$Caddyfile = 'C:\ATI\ayarlar\Caddyfile',
    [string]$Caddy = 'C:\ATI\araclar\caddy.exe',
    [switch]$Kaldir
)
# Caddy bilgi mesajlarını stderr'e yazar; PowerShell 5.1 bunları hata sanmasın diye 'Continue'.
# Başarı her adımda çıkış koduyla ($LASTEXITCODE) denetlenir.
$ErrorActionPreference = 'Continue'
$bas = '# >>> futbol.canarslan.net.tr (Match Intelligence; deploy/windows/caddy-ekle.ps1)'
$son = '# <<< futbol.canarslan.net.tr'
$blok = @"

$bas
futbol.canarslan.net.tr {
	encode zstd gzip
	@ic path /metrics /metrics/*
	respond @ic 404
	request_body {
		max_size 1MB
	}
	reverse_proxy 127.0.0.1:3080 {
		header_up X-Forwarded-For {remote_host}
	}
}
$son
"@
foreach ($f in @($Caddyfile, $Caddy)) { if (-not (Test-Path $f)) { Write-Host "HATA: bulunamadı: $f" -ForegroundColor Red; exit 1 } }
$utf8 = New-Object Text.UTF8Encoding($false)
$eski = [IO.File]::ReadAllText($Caddyfile)
$yedek = "$Caddyfile.yedek-" + (Get-Date -Format 'yyyyMMdd-HHmmss')
Copy-Item $Caddyfile $yedek -ErrorAction Stop
Write-Host "Yedek: $yedek"

if ($Kaldir) {
    $i = $eski.IndexOf($bas); $j = $eski.IndexOf($son)
    if ($i -lt 0) { Write-Host 'Futbol bloğu zaten yok.'; exit 0 }
    $yeni = $eski.Substring(0, $i).TrimEnd() + [Environment]::NewLine + $eski.Substring($j + $son.Length).TrimStart()
} else {
    if ($eski.Contains($bas)) { Write-Host 'Futbol bloğu zaten ekli; değişiklik yok.'; exit 0 }
    $yeni = $eski.TrimEnd() + [Environment]::NewLine + $blok + [Environment]::NewLine
}
[IO.File]::WriteAllText($Caddyfile, $yeni, $utf8)

function Geri-Al([string]$neden) {
    [IO.File]::WriteAllText($Caddyfile, $eski, $utf8)
    & $Caddy reload --config $Caddyfile --adapter caddyfile | Out-Null
    Write-Host "HATA: $neden — Caddyfile eski hâline döndürüldü, siteleriniz etkilenmedi." -ForegroundColor Red
    exit 1
}
& $Caddy validate --config $Caddyfile --adapter caddyfile | Out-Host
if ($LASTEXITCODE -ne 0) { Geri-Al 'yeni ayar doğrulanamadı' }
& $Caddy reload --config $Caddyfile --adapter caddyfile | Out-Host
if ($LASTEXITCODE -ne 0) { Geri-Al 'Caddy yeniden yüklenemedi' }
if ($Kaldir) { Write-Host 'Futbol bloğu kaldırıldı.' -ForegroundColor Green }
else { Write-Host 'Eklendi. DNS kaydı hazırsa Caddy sertifikayı birkaç dakika içinde kendisi alır.' -ForegroundColor Green }
