# futbol.canarslan.net.tr yönetim komutları (Yönetici PowerShell):
#   futbol.ps1 durum | yonetici EPOSTA "AD SOYAD" | parola EPOSTA [-MfaSifirla] | yedek | durdur | baslat | yeniden-baslat | loglar [api|web|tahmin]
#              tahmin-hazirla [-Sezon 4] [-Deneme 25] [-SadeceEgit] [-Lig AD] | tahmin | model-durum | kaldir -Onay [-VeriyiSil]
param(
    [Parameter(Position = 0)][string]$Komut = 'durum',
    [Parameter(Position = 1)][string]$A1,
    [Parameter(Position = 2)][string]$A2,
    [switch]$Onay, [switch]$VeriyiSil, [switch]$BellekUyarisiniGec, [switch]$SadeceEgit, [switch]$MfaSifirla,
    [int]$Sezon = 4, [int]$Deneme = 25, [string]$Lig
)
. (Join-Path $PSScriptRoot 'ortak.ps1')
if (-not (Yonetici-mi)) { Dur 'Yönetici PowerShell gerekli' }

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
    'parola' {
        # Parolasını unutan (e-posta gönderimi henüz yok) hesap için tek kullanımlık bağlantı.
        # -MfaSifirla: telefon/doğrulama uygulaması kaybolduysa iki adımlı doğrulamayı da sıfırlar.
        if (-not $A1) { Dur 'kullanım: futbol.ps1 parola EPOSTA [-MfaSifirla]' }
        Ortam-Yukle
        if ($MfaSifirla) { Mi-Admin password-link --email $A1 --reset-mfa } else { Mi-Admin password-link --email $A1 }
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
        if (-not $SadeceEgit) { & (Join-Path $PSScriptRoot 'futbol.ps1') yeniden-baslat }
        Ortam-Yukle
        $bekle = 8   # ücretsiz paket: dakikada 10 istek

        # 4) Yaklaşan ve son günlerin maçları (ligler buradan oluşur).
        # -SadeceEgit: veri zaten yüklü; indirme atlanır, yalnızca eğitim ve tahmin yapılır.
        if (-not $SadeceEgit) {
            Yaz 'Maç takvimi çekiliyor (dün … 8 gün sonrası)'
            foreach ($g in -1..8) {
                $gun = (Get-Date).ToUniversalTime().AddDays($g).ToString('yyyy-MM-dd')
                Mi-Admin football-sync fixtures_date --date $gun | Select-Object -Last 3 | Out-Host
                Start-Sleep $bekle
            }
        }
        Sql-Dosya 'futbol' (Env-Deger 'FUTBOL_DB_PASSWORD') "UPDATE football_competitions SET is_active = true WHERE provider = '$saglayici';"
        $ligler = @(Sql-Satirlar "SELECT id || '|' || name FROM football_competitions WHERE provider = '$saglayici' ORDER BY id")
        if (-not $ligler) { Dur 'Hiç lig gelmedi. Anahtarı ve günlüğü kontrol edin: futbol.ps1 loglar api' }
        if ($Lig) {
            # -Lig: yalnızca adı eşleşen lig(ler) (ör. -Lig "Champions"); diğerlerine dokunulmaz.
            $ligler = @($ligler | Where-Object { $_.Split('|', 2)[1] -like "*$Lig*" })
            if (-not $ligler) { Dur "'$Lig' adında lig yok. Lig adları için: futbol.ps1 model-durum" }
        }
        Yaz ("Takip edilen ligler: " + (($ligler | ForEach-Object { $_.Split('|')[1] }) -join ', '))

        # 5) Geçmiş sezonlar (model eğitimi için).
        $simdi = (Get-Date).ToUniversalTime()
        $buSezon = $simdi.Year; if ($simdi.Month -lt 7) { $buSezon-- }
        foreach ($satir in $ligler) {
            if ($SadeceEgit) { break }
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
            if ($kod -eq 0) { $sonuc += "${ad}: eğitildi" } else { $sonuc += "${ad}: eğitilemedi (çıkış kodu $kod; ayrıntı yukarıda)" }
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
    'model-durum' {
        # Lig başına model ve tahmin özeti (yalnızca okur).
        Sql-Dosya 'futbol' (Env-Deger 'FUTBOL_DB_PASSWORD') @'
\pset footer off
\qecho 'Lig başına modeller ve önümüzdeki 7 günün tahminleri:'
WITH fx AS (SELECT f.id, f.status, f.kickoff_at, s.competition_id
            FROM football_fixtures f JOIN football_seasons s ON s.id = f.season_id)
SELECT c.name AS lig,
       (SELECT max(v.id) FROM ml_model_versions v WHERE v.scope_key = 'competition:' || c.id AND v.status = 'champion') AS sampiyon,
       (SELECT round((v.metrics -> 'test' -> 'ensemble' ->> 'log_loss')::numeric, 3) FROM ml_model_versions v
         WHERE v.scope_key = 'competition:' || c.id AND v.status = 'champion') AS sampiyon_ll,
       (SELECT count(*) FROM ml_model_versions v WHERE v.scope_key = 'competition:' || c.id AND v.status = 'challenger') AS aday,
       (SELECT min(round((v.metrics -> 'test' -> 'ensemble' ->> 'log_loss')::numeric, 3)) FROM ml_model_versions v
         WHERE v.scope_key = 'competition:' || c.id AND v.status = 'challenger') AS en_iyi_aday_ll,
       (SELECT count(*) FROM fx f WHERE f.competition_id = c.id AND f.status = 'finished') AS biten_mac,
       (SELECT count(*) FROM fx f WHERE f.competition_id = c.id AND f.kickoff_at > now() AND f.kickoff_at < now() + interval '7 days') AS yaklasan_mac,
       (SELECT count(DISTINCT p.fixture_id) FROM ml_predictions p JOIN fx f ON f.id = p.fixture_id
         WHERE f.competition_id = c.id AND p.kickoff_at > now() AND p.status = 'published') AS yayinlanan,
       (SELECT count(DISTINCT p.fixture_id) FROM ml_predictions p JOIN fx f ON f.id = p.fixture_id
         WHERE f.competition_id = c.id AND p.kickoff_at > now() AND p.status = 'abstained') AS cekimser
FROM football_competitions c WHERE c.is_active ORDER BY c.name;
\qecho 'Modeller (en yeni 12; ll = test log loss, düşük daha iyi):'
SELECT v.id, c.name AS lig, v.status AS durum, v.created_at::timestamp(0) AS egitildi, v.n_rows AS satir,
       round((v.metrics -> 'test' -> 'ensemble' ->> 'log_loss')::numeric, 3) AS test_log_loss,
       round((v.metrics -> 'test' -> 'ensemble' ->> 'accuracy')::numeric, 3) AS test_dogruluk
FROM ml_model_versions v
LEFT JOIN football_competitions c ON v.scope_key = 'competition:' || c.id
ORDER BY v.id DESC LIMIT 12;
\qecho 'Çekimser kalma nedenleri (yaklaşan maçlar):'
SELECT r ->> 'code' AS neden, min(r ->> 'message') AS aciklama, count(*) AS adet
FROM ml_predictions p, jsonb_array_elements(p.abstain_reasons) r
WHERE p.kickoff_at > now() GROUP BY 1 ORDER BY 3 DESC;
'@
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
