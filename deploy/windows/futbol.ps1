# futbol.canarslan.net.tr yönetim komutları (Yönetici PowerShell):
#   futbol.ps1 durum | yonetici EPOSTA "AD SOYAD" | yedek | durdur | baslat | yeniden-baslat | loglar [api|web|tahmin]
#              tahmin-hazirla [-Sezon 4] [-Deneme 25] | tahmin | kaldir -Onay [-VeriyiSil]
param(
    [Parameter(Position = 0)][string]$Komut = 'durum',
    [Parameter(Position = 1)][string]$A1,
    [Parameter(Position = 2)][string]$A2,
    [switch]$Onay, [switch]$VeriyiSil, [switch]$BellekUyarisiniGec,
    [int]$Sezon = 4, [int]$Deneme = 25
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
    'tahmin' {
        if (-not (Test-Path $MlPy)) { Dur 'Tahmin motoru kurulu değil: önce futbol.ps1 tahmin-hazirla' }
        & (Join-Path $PSScriptRoot 'tahmin.ps1')
        Get-Content (Join-Path $Loglar 'tahmin.log') -Tail 4
    }
    'tahmin-hazirla' {
        # 1) Veri sağlayıcısı ayarlı mı (anahtarı kullanıcı futbol.env'e kendisi yazar).
        $saglayici = Env-Deger 'MI_FOOTBALL_PROVIDER'; $anahtar = Env-Deger 'MI_FOOTBALL_API_KEY'
        if (-not $saglayici -or $saglayici -eq 'none' -or -not $anahtar) {
            Dur ("Veri anahtarı yok. notepad $EnvDosya ile MI_FOOTBALL_PROVIDER=football_data ve " +
                 "MI_FOOTBALL_API_KEY=<anahtarınız> satırlarını yazın, kaydedin, sonra tekrar çalıştırın.")
        }
        $bos = Bos-Bellek-MB
        if ($bos -lt 700 -and -not $BellekUyarisiniGec) {
            Dur "Bellek az ($bos MB). Model eğitimi botunuzu yavaşlatabilir; açık Claude/Chrome/ChatGPT'yi kapatıp tekrar deneyin."
        }
        Env-Ekle 'MI_FOOTBALL_LIVE_ENABLED' 'false'
        Env-Ekle 'MI_FOOTBALL_DAILY_BUDGET' '2000'
        Env-Ekle 'MI_FOOTBALL_MINUTE_BUDGET' '8'

        # 2) Tahmin motoru (ayrı Python ortamı, ~300 MB).
        Yaz 'Tahmin motoru kuruluyor (ilk seferde birkaç dakika)'
        Uv-Ortam
        Push-Location (Join-Path $Proje 'ml')
        try { & $UvExe sync --locked --no-dev --python 3.12 | Out-Host } finally { Pop-Location }
        if (-not (Test-Path $MlPy)) { Dur 'Tahmin motoru kurulamadı' }
        & $UvExe cache clean | Out-Null

        # 3) Hizmetler yeni ayarla yeniden başlar (zamanlayıcı veri işlerini açar).
        & (Join-Path $PSScriptRoot 'futbol.ps1') yeniden-baslat
        Ortam-Yukle
        $bekle = 8   # ücretsiz paket: dakikada 10 istek

        # 4) Yaklaşan ve son günlerin maçları (ligler buradan oluşur).
        Yaz 'Maç takvimi çekiliyor (dün … 8 gün sonrası)'
        foreach ($g in -1..8) {
            $gun = (Get-Date).ToUniversalTime().AddDays($g).ToString('yyyy-MM-dd')
            Mi-Admin football-sync fixtures_date --date $gun | Select-Object -Last 3 | Out-Host
            Start-Sleep $bekle
        }
        $env:PGPASSWORD = Env-Deger 'FUTBOL_DB_PASSWORD'
        $psql = Join-Path $PgBin 'psql.exe'
        & $psql -h 127.0.0.1 -p $PgPort -U futbol -d futbol -qc "UPDATE football_competitions SET is_active = true WHERE provider = '$saglayici'" | Out-Null
        $ligler = & $psql -h 127.0.0.1 -p $PgPort -U futbol -d futbol -tAc "SELECT id || '|' || name FROM football_competitions WHERE provider = '$saglayici' ORDER BY id"
        Remove-Item Env:PGPASSWORD
        if (-not $ligler) { Dur 'Hiç lig gelmedi. Anahtarı ve günlüğü kontrol edin: futbol.ps1 loglar api' }
        Yaz ("Takip edilen ligler: " + (($ligler | ForEach-Object { $_.Split('|')[1] }) -join ', '))

        # 5) Geçmiş sezonlar (model eğitimi için).
        $simdi = (Get-Date).ToUniversalTime()
        $buSezon = $simdi.Year; if ($simdi.Month -lt 7) { $buSezon-- }
        foreach ($satir in $ligler) {
            $id, $ad = $satir.Split('|', 2)
            foreach ($y in ($buSezon - $Sezon + 1)..$buSezon) {
                Yaz "$ad — $y sezonu"
                Mi-Admin football-sync season_backfill --competition-id $id --season $y | Select-Object -Last 2 | Out-Host
                Start-Sleep $bekle
            }
        }

        # 6) Lig başına model eğitimi (düşük öncelik; ilk model kendiliğinden şampiyon olur).
        $sonuc = @()
        foreach ($satir in $ligler) {
            $id, $ad = $satir.Split('|', 2)
            Yaz "Model eğitiliyor: $ad (birkaç dakika sürebilir)"
            $kod = Dusuk-Oncelikle $MlPy @('-m', 'mi_ml.cli', 'train', '--competition-id', "$id", '--trials', "$Deneme")
            if ($kod -eq 0) { $sonuc += "${ad}: eğitildi" } else { $sonuc += "${ad}: eğitilemedi (yetersiz veri olabilir)" }
        }

        # 7) Otomatik tahmin görevi (30 dakikada bir) ve ilk tahminler.
        $kim = New-ScheduledTaskPrincipal -UserId (Ag-Hizmeti-Adi) -LogonType ServiceAccount
        $ayar = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 25) -MultipleInstances IgnoreNew
        $tetik = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30)
        $is = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'tahmin.ps1')`""
        Register-ScheduledTask -TaskPath $GorevYolu -TaskName 'Futbol-tahmin' -Action $is -Principal $kim -Settings $ayar `
            -Trigger $tetik -Force | Out-Null
        & (Join-Path $PSScriptRoot 'tahmin.ps1')
        Write-Host ''
        Yaz 'Sonuç:'
        $sonuc | ForEach-Object { Write-Host "  $_" }
        Get-Content (Join-Path $Loglar 'tahmin.log') -Tail 2
        Yaz 'Tahminler 30 dakikada bir otomatik yenilenir. Model Lab: https://futbol.canarslan.net.tr/yonetim/modeller'
    }
    'loglar' {
        $h = 'api'; if ($A1) { $h = $A1 }
        if ($h -eq 'tahmin') { Get-Content (Join-Path $Loglar 'tahmin.log') -Tail 40 -ErrorAction SilentlyContinue; break }
        Get-Content (Join-Path $Loglar "$h.log") -Tail 60 -ErrorAction SilentlyContinue
        Get-Content (Join-Path $Loglar "$h.hata.log") -Tail 30 -ErrorAction SilentlyContinue
    }
    'kaldir' {
        if (-not $Onay) { Dur 'Kaldırmak için -Onay ekleyin (veriyi de silmek için ayrıca -VeriyiSil)' }
        Surecleri-Durdur
        foreach ($h in @('api', 'web', 'tahmin')) { Unregister-ScheduledTask -TaskPath $GorevYolu -TaskName "Futbol-$h" -Confirm:$false -ErrorAction SilentlyContinue }
        if (Get-Service $PgServis -ErrorAction SilentlyContinue) {
            Stop-Service $PgServis -ErrorAction SilentlyContinue
            & (Join-Path $PgBin 'pg_ctl.exe') unregister -N $PgServis | Out-Host
        }
        Yaz 'Hizmetler kaldırıldı. Caddy bloğu için: caddy-ekle.ps1 -Kaldir'
        if ($VeriyiSil) { Remove-Item $Veri -Recurse -Force; Yaz "Veri silindi: $Veri" } else { Yaz "Veri korundu: $Veri" }
    }
    default { Dur "Bilinmeyen komut: $Komut" }
}
