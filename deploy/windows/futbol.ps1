# futbol.canarslan.net.tr yönetim komutları (Yönetici PowerShell):
#   futbol.ps1 durum | yonetici EPOSTA "AD SOYAD" | yedek | durdur | baslat | yeniden-baslat | loglar [api|web] | kaldir -Onay [-VeriyiSil]
param(
    [Parameter(Position = 0)][string]$Komut = 'durum',
    [Parameter(Position = 1)][string]$A1,
    [Parameter(Position = 2)][string]$A2,
    [switch]$Onay, [switch]$VeriyiSil
)
. (Join-Path $PSScriptRoot 'ortak.ps1')
if (-not (Yonetici-mi)) { Dur 'Yönetici PowerShell gerekli' }

function Surecleri-Durdur {
    foreach ($h in @('api', 'web')) {
        Stop-ScheduledTask -TaskPath $GorevYolu -TaskName "Futbol-$h" -ErrorAction SilentlyContinue
        $pf = Join-Path $PidDir "$h.pid"
        if (Test-Path $pf) {
            $id = [int](Get-Content $pf)
            $p = Get-Process -Id $id -ErrorAction SilentlyContinue
            # Yalnızca futbol'un kendi sürecini (ve alt süreçlerini) kapatır.
            if ($p -and $p.ProcessName -in @('node', 'python')) { taskkill.exe /PID $id /T /F | Out-Null }
            Remove-Item $pf -Force
        }
    }
}
function Saglik {
    try { (Invoke-WebRequest "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 'yanıt yok' }
}
function Bekle-Hazir {
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $a = (Invoke-WebRequest "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 2).StatusCode
            $w = (Invoke-WebRequest "http://127.0.0.1:$WebPort/giris" -UseBasicParsing -TimeoutSec 5).StatusCode
            if ($a -eq 200 -and $w -eq 200) { Yaz "Hazır: API $a, web $w"; return }
        } catch {}
        Start-Sleep 2
    }
    Uyar "Hizmetler 2 dakikada hazır olmadı. Günlükler: $Loglar"
}

switch ($Komut) {
    'durum' {
        Get-Service $PgServis -ErrorAction SilentlyContinue | Select-Object Name, Status | Format-Table -AutoSize
        Get-ScheduledTask -TaskPath $GorevYolu -ErrorAction SilentlyContinue | Select-Object TaskName, State | Format-Table -AutoSize
        Write-Host "API sağlık: $(Saglik)"
        foreach ($h in @('api', 'web')) {
            $pf = Join-Path $PidDir "$h.pid"
            if (Test-Path $pf) {
                $p = Get-Process -Id ([int](Get-Content $pf)) -ErrorAction SilentlyContinue
                if ($p) { Write-Host ("{0}: çalışıyor, bellek {1} MB" -f $h, [int]($p.WorkingSet64 / 1MB)) } else { Write-Host "${h}: çalışmıyor" }
            }
        }
        Write-Host "Kullanılabilir bellek: $(Bos-Bellek-MB) MB"
        $env:PGPASSWORD = Env-Deger 'FUTBOL_DB_PASSWORD'
        Write-Host 'Son yedekler:'
        & (Join-Path $PgBin 'psql.exe') -h 127.0.0.1 -p $PgPort -U futbol -d futbol -tAc "SELECT created_at::timestamp(0), status, coalesce(verify_ok::text,'-'), file_name FROM backups ORDER BY id DESC LIMIT 3"
        Remove-Item Env:PGPASSWORD
    }
    'yonetici' {
        if (-not $A1 -or -not $A2) { Dur 'kullanım: futbol.ps1 yonetici EPOSTA "AD SOYAD"' }
        Ortam-Yukle; Mi-Admin bootstrap --email $A1 --name $A2
    }
    'yedek' { Ortam-Yukle; Mi-Admin backup }
    'durdur' { Surecleri-Durdur; Yaz 'Futbol durduruldu (veritabanı hizmeti açık kalır)' }
    'baslat' {
        if ((Get-Service $PgServis).Status -ne 'Running') { Start-Service $PgServis }
        foreach ($h in @('api', 'web')) { Start-ScheduledTask -TaskPath $GorevYolu -TaskName "Futbol-$h" }
        Bekle-Hazir
    }
    'yeniden-baslat' {
        Surecleri-Durdur
        if ((Get-Service $PgServis).Status -ne 'Running') { Start-Service $PgServis }
        foreach ($h in @('api', 'web')) { Start-ScheduledTask -TaskPath $GorevYolu -TaskName "Futbol-$h" }
        Bekle-Hazir
    }
    'loglar' {
        $h = 'api'; if ($A1) { $h = $A1 }
        Get-Content (Join-Path $Loglar "$h.log") -Tail 60 -ErrorAction SilentlyContinue
        Get-Content (Join-Path $Loglar "$h.hata.log") -Tail 30 -ErrorAction SilentlyContinue
    }
    'kaldir' {
        if (-not $Onay) { Dur 'Kaldırmak için -Onay ekleyin (veriyi de silmek için ayrıca -VeriyiSil)' }
        Surecleri-Durdur
        foreach ($h in @('api', 'web')) { Unregister-ScheduledTask -TaskPath $GorevYolu -TaskName "Futbol-$h" -Confirm:$false -ErrorAction SilentlyContinue }
        if (Get-Service $PgServis -ErrorAction SilentlyContinue) {
            Stop-Service $PgServis -ErrorAction SilentlyContinue
            & (Join-Path $PgBin 'pg_ctl.exe') unregister -N $PgServis | Out-Host
        }
        Yaz 'Hizmetler kaldırıldı. Caddy bloğu için: caddy-ekle.ps1 -Kaldir'
        if ($VeriyiSil) { Remove-Item $Veri -Recurse -Force; Yaz "Veri silindi: $Veri" } else { Yaz "Veri korundu: $Veri" }
    }
    default { Dur "Bilinmeyen komut: $Komut" }
}
