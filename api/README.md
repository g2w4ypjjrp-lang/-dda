# mi-api — Match Intelligence AI API servisi

FastAPI + SQLAlchemy 2 (async, psycopg3) + Alembic + PostgreSQL 16 + Redis.

```bash
uv sync
export MI_DATABASE_URL=postgresql://mi:mi@127.0.0.1:5432/mi
export MI_REDIS_URL=redis://127.0.0.1:6379/0
export MI_SECRET_KEK=$(python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())")
uv run mi-admin migrate
uv run mi-admin bootstrap --email yonetici@ornek.com --name "Ad Soyad"
uv run mi-api --port 8080
```

Testler gerçek PostgreSQL (ve varsa Redis) üzerinde çalışır:

```bash
MI_TEST_DATABASE_URL=postgresql://mi_test:mi_test@127.0.0.1:5432/mi_test \
MI_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run pytest
```

Ayrıntılar: [`../docs/02-faz1-raporu.md`](../docs/02-faz1-raporu.md).
