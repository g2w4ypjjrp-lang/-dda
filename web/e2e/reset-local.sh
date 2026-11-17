#!/usr/bin/env bash
# Yerel E2E: test veritabanını sıfırlar, geçişleri ve demo verisini yükler (yalnızca test ortamı).
# Kullanım: MI_DATABASE_URL=postgresql://.../mi_e2e ./e2e/reset-local.sh   (API'yi sonra yeniden başlatın)
set -euo pipefail
here="$(cd "$(dirname "$0")/../.." && pwd)"
db="${MI_DATABASE_URL:?MI_DATABASE_URL gerekli}"
admin="${db%/*}/postgres"
name="${db##*/}"
psql "$admin" -qc "DROP DATABASE IF EXISTS \"$name\" WITH (FORCE)" -c "CREATE DATABASE \"$name\""
(cd "$here/api" && uv run mi-admin migrate)
(cd "$here/ml" && MI_ENVIRONMENT=test uv run python scripts/seed_demo.py)
