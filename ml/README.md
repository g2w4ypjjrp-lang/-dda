# mi-ml — Match Intelligence AI tahmin motoru

Olasılık modelleri (Poisson, Dixon-Coles, Elo), sızıntısız özellik üretimi, LightGBM + Optuna,
ensemble, kalibrasyon, walk-forward backtest, belirsizlik ve çekimserlik kuralları.
Şema ve API `../api` paketindedir; bu paket eğitim ve tahmin üretimini yapar.

```bash
uv sync
uv run pytest          # saf matematik testleri; veritabanı testleri MI_TEST_DATABASE_URL ile
uv run mi-ml --help
```

Ayrıntılar: [`../docs/04-faz3-raporu.md`](../docs/04-faz3-raporu.md).
