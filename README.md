# Match Intelligence AI

Gerçek futbol verileriyle çalışan, olasılık ve belirsizliği açıkça gösteren bir futbol istihbarat ve
analitik SaaS platformu. Ürün analiz ve **sanal** simülasyon sunar. Gerçek bahis işlemi yapmaz ve
kazanç garantisi vermez.

| Bileşen | Klasör | Durum |
|---|---|---|
| API servisi | [`api/`](api/) | ✅ Faz 1: kimlik doğrulama, MFA, RBAC (7 rol), denetim kaydı, loglama, hız sınırı |
| Futbol veri altyapısı | [`api/src/mi_api/football/`](api/src/mi_api/football/) | ✅ Faz 2: API-Football ve football-data.org uyarlayıcıları, kota yönetimi, Celery işçisi; gerçek veri sağlayıcı anahtarıyla (M-G1) |
| AI / tahmin motoru | [`ml/`](ml/) | ✅ Faz 3: Poisson, Dixon-Coles, Elo, LightGBM + Optuna, ensemble, kalibrasyon, walk-forward backtest, belirsizlik ve çekimserlik, değiştirilemez tahmin kaydı |
| Web uygulaması ve 10 tasarım | `web/` | ⏳ Faz 7–8 |

## Belgeler

0. [Teknik denetim raporu](docs/00-teknik-denetim.md)
1. [Geliştirme yol haritası ve onay kapıları](docs/01-yol-haritasi.md)
2. [Faz 1 raporu](docs/02-faz1-raporu.md)
3. [Faz 2 raporu](docs/03-faz2-raporu.md)
4. [Faz 3 raporu](docs/04-faz3-raporu.md)

## Hızlı başlangıç

```bash
cp .env.example .env        # MI_DB_PASSWORD ve MI_SECRET_KEK değerlerini doldurun
docker compose up --build   # PostgreSQL + Redis + geçişler + API (http://127.0.0.1:8080)
docker compose run --rm api mi-admin bootstrap --email <e-posta> --name "<Ad Soyad>"
```

Docker olmadan geliştirme ve testler için: [`api/README.md`](api/README.md).

## Lisans

Tescilli yazılım. Tüm hakları saklıdır.
