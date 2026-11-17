# Match Intelligence AI — ML imajı (eğitim, tahmin, ML işçisi). Derleme bağlamı: depo kökü.
#   docker build -f ml/Dockerfile -t mi-ml .
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY api /app/api
COPY ml/pyproject.toml ml/uv.lock ml/README.md /app/ml/
WORKDIR /app/ml
RUN uv sync --locked --no-dev --no-install-project
COPY ml/src /app/ml/src
RUN uv sync --locked --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home /app mi
COPY --from=build --chown=mi:mi /app /app
WORKDIR /app/ml
ENV PATH="/app/ml/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER mi
CMD ["celery", "-A", "mi_ml.tasks", "worker", "-Q", "ml", "--loglevel=INFO", "--concurrency=1"]
