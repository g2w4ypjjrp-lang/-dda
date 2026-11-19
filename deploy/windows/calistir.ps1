# Hizmet başlatıcı: Zamanlanmış Görev (Futbol-API / Futbol-Web) bunu çalıştırır.
# Süreç çökerse bekleyip yeniden başlatır; işlemci önceliği "normalin altı" (botunuz önceliklidir).
param([Parameter(Mandatory = $true)][ValidateSet('api', 'web')][string]$Hizmet)
. (Join-Path $PSScriptRoot 'ortak.ps1')
$ErrorActionPreference = 'Continue'
Ortam-Yukle
New-Item -ItemType Directory -Force -Path $Loglar, $PidDir | Out-Null

if ($Hizmet -eq 'api') {
    $exe = $PyExe
    $arg = @('-m', 'mi_api.server', '--host', '127.0.0.1', '--port', "$ApiPort")
} else {
    $env:PORT = "$WebPort"; $env:HOSTNAME = '127.0.0.1'; $env:NODE_ENV = 'production'
    $env:NEXT_TELEMETRY_DISABLED = '1'
    # Sunucu tarafı istekler (ör. yayımlanmış tasarımlar) API'yi burada bulur; yoksa 8080 denenir,
    # ulaşılamaz ve site yerleşik varsayılan temaya düşer.
    $env:MI_API_URL = "http://127.0.0.1:$ApiPort"
    $exe = (Get-Command node.exe -ErrorAction Stop).Source
    $arg = @('--max-old-space-size=192', ('"' + (Join-Path $WebDir 'server.js') + '"'))
}
$out = Join-Path $Loglar "$Hizmet.log"
$err = Join-Path $Loglar "$Hizmet.hata.log"
$bekle = 5
while ($true) {
    foreach ($f in @($out, $err)) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 20MB) { Move-Item $f "$f.1" -Force }
    }
    $p = Start-Process -FilePath $exe -ArgumentList $arg -WorkingDirectory $Kok -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    try { $p.PriorityClass = 'BelowNormal' } catch {}
    Set-Content -Path (Join-Path $PidDir "$Hizmet.pid") -Value $p.Id
    $basla = Get-Date
    $p.WaitForExit()
    Add-Content -Path $err -Value ("{0} süreç kapandı (çıkış {1}); {2} sn sonra yeniden" -f (Get-Date -Format s), $p.ExitCode, $bekle)
    if (((Get-Date) - $basla).TotalMinutes -gt 5) { $bekle = 5 } else { $bekle = [Math]::Min($bekle * 2, 60) }
    Start-Sleep -Seconds $bekle
}
