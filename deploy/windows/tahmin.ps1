# Zamanlanmış Görev (Futbol-tahmin, 30 dakikada bir): şampiyon modellerle yaklaşan maçların
# tahminini yazar ve biten maçların tahminlerini sonuçlandırır. Düşük öncelikle çalışır.
. (Join-Path $PSScriptRoot 'ortak.ps1')
$ErrorActionPreference = 'Continue'
Ortam-Yukle
New-Item -ItemType Directory -Force -Path $Loglar | Out-Null
$log = Join-Path $Loglar 'tahmin.log'
if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) { Move-Item $log "$log.1" -Force }
foreach ($is in @('predict-active', 'settle')) {
    $out = Join-Path $env:TEMP "futbol-tahmin-$is.txt"
    $p = Start-Process -FilePath $MlPy -ArgumentList @('-m', 'mi_ml.cli', $is) -WorkingDirectory $Kok `
        -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.hata"
    try { $p.PriorityClass = 'BelowNormal' } catch {}
    $p.WaitForExit()
    $ozet = (Get-Content $out -ErrorAction SilentlyContinue | Select-Object -Last 1)
    Add-Content -Path $log -Value ("{0} {1} çıkış={2} {3}" -f (Get-Date -Format s), $is, $p.ExitCode, $ozet)
    if ($p.ExitCode -ne 0) { Get-Content "$out.hata" -Tail 20 -ErrorAction SilentlyContinue | Add-Content -Path $log }
    Remove-Item $out, "$out.hata" -Force -ErrorAction SilentlyContinue
}
