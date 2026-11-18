# Match Intelligence AI

Gerçek futbol verileriyle çalışan, olasılık ve belirsizliği açıkça gösteren bir futbol istihbarat ve
analitik SaaS platformu. Ürün analiz ve **sanal** simülasyon sunar. Gerçek bahis işlemi yapmaz ve
kazanç garantisi vermez.

| Bileşen | Klasör | Durum |
|---|---|---|
| API servisi | [`api/`](api/) | ✅ Faz 1: kimlik doğrulama, MFA, RBAC (7 rol), denetim kaydı, loglama, hız sınırı |
| Futbol veri altyapısı | [`api/src/mi_api/football/`](api/src/mi_api/football/) | ✅ Faz 2: API-Football ve football-data.org uyarlayıcıları, kota yönetimi, Celery işçisi; gerçek veri sağlayıcı anahtarıyla (M-G1) |
| AI / tahmin motoru | [`ml/`](ml/) | ✅ Faz 3: Poisson, Dixon-Coles, Elo, LightGBM + Optuna, ensemble, kalibrasyon, walk-forward backtest, belirsizlik ve çekimserlik, değiştirilemez tahmin kaydı |
| Paket, ödeme, lisans | [`api/src/mi_api/billing/`](api/src/mi_api/billing/) | ✅ Faz 6: FREE/PRO/ELITE hakları (backend'de), abonelik, PayTR/iyzico/simülatör (imzalı, idempotent), iade, lisans anahtarları; canlı ödeme M-G5 ile |
| Web uygulaması | [`web/`](web/) | ✅ Site, maç merkezi, maç detayı + AI analizi, hesap + MFA, kullanıcı paneli, yönetim paneli (Command Center, Veri Merkezi, Model Lab, Kullanıcılar, Denetim). On tasarım sistemi (kabuk, ana sayfa, liste, kart, tipografi ayrı) ve Design Studio (önizleme, düzenleme, yayın, sürüm, geri alma) |

## Belgeler

0. [Teknik denetim raporu](docs/00-teknik-denetim.md)
1. [Geliştirme yol haritası ve onay kapıları](docs/01-yol-haritasi.md)
2. [Faz 1 raporu](docs/02-faz1-raporu.md)
3. [Faz 2 raporu](docs/03-faz2-raporu.md)
4. [Faz 3 raporu](docs/04-faz3-raporu.md)
5. [Arayüz raporu](docs/05-arayuz-raporu.md)
6. [Faz 4 raporu — kupon motoru](docs/06-faz4-raporu.md)
7. [Faz 5 raporu — sanal portföy](docs/07-faz5-raporu.md)
8. [Faz 6 raporu — paketler, ödeme, lisans](docs/08-faz6-raporu.md)
9. [İlk yarı modeli ve kupona ekle](docs/09-ilk-yari-raporu.md)
10. [Faz 8 raporu — on tasarım ve Design Studio](docs/10-faz8-raporu.md)
11. [Faz 9 raporu — süper yönetici modülleri](docs/11-faz9-raporu.md)
12. [Faz 7 kalanları — kişisel panel, bildirimler, içerik, PWA](docs/12-faz7-raporu.md)
13. [Faz 10 raporu — yayın öncesi: güvenlik, yedek, izleme, dağıtım](docs/13-faz10-raporu.md)
14. [Çalıştırma kılavuzu (üretim)](docs/calistirma-kilavuzu.md)
15. [futbol.canarslan.net.tr — Linux sunucuya ayrık kurulum (Docker)](docs/vds-kurulum.md)
16. [futbol.canarslan.net.tr — Windows VDS'ye kurulum (botla aynı sunucu)](docs/windows-kurulum.md)

## Hızlı başlangıç

```bash
cp .env.example .env        # MI_DB_PASSWORD ve MI_SECRET_KEK değerlerini doldurun
docker compose up --build   # PostgreSQL + Redis + geçişler + API (http://127.0.0.1:8080)
docker compose run --rm api mi-admin bootstrap --email <e-posta> --name "<Ad Soyad>"
# Web: http://127.0.0.1:3000 · Yönetim: http://127.0.0.1:3000/yonetim
```

Yerel geliştirme (Docker olmadan): API `uv run mi-api --port 8080`, web `cd web && npm ci && npm run dev`
(`MI_API_URL` varsayılanı `http://127.0.0.1:8080`). Test ortamı için kurgusal demo verisi:
`cd ml && MI_ENVIRONMENT=test uv run python scripts/seed_demo.py` (üretimde çalışmaz).

Docker olmadan geliştirme ve testler için: [`api/README.md`](api/README.md).

## Lisans

Tescilli yazılım. Tüm hakları saklıdır.
