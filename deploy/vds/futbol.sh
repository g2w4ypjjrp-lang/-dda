#!/usr/bin/env bash
# futbol.canarslan.net.tr yönetim betiği. Yalnızca bu klasörü ve "futbol" Docker projesini
# (futbol-* kapsayıcılar, futbol_* ağ/birimler) kullanır; sunucudaki başka hiçbir şeye dokunmaz.
#
#   ./deploy/vds/futbol.sh kur                 # ilk kurulum / yeniden başlatma (gizli değerleri üretir)
#   ./deploy/vds/futbol.sh durum               # kapsayıcılar, sağlık, son yedek
#   ./deploy/vds/futbol.sh yonetici EPOSTA "Ad Soyad"   # ilk süper yönetici (tek kullanımlık bağlantı)
#   ./deploy/vds/futbol.sh yedek               # elle yedek + geri yükleme doğrulaması
#   ./deploy/vds/futbol.sh guncelle            # git çek → yedek → yeniden derle → başlat
#   ./deploy/vds/futbol.sh loglar [hizmet]     # günlükler (api, web, worker, beat, postgres, redis)
#   ./deploy/vds/futbol.sh durdur              # tüm futbol kapsayıcılarını durdurur (veri korunur)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
ENV_FILE="$HERE/.env"
dc() { docker compose -p futbol -f "$HERE/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }
die() { echo "HATA: $*" >&2; exit 1; }
rand() { head -c 32 /dev/urandom | base64 | tr -d '\n'; }
pw() { head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32; }
get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }
setv() { # yalnızca boş değeri doldurur
  if grep -qE "^$1=$" "$ENV_FILE"; then sed -i "s|^$1=$|$1=$2|" "$ENV_FILE"; fi
}

need_docker() {
  command -v docker >/dev/null || die "Docker kurulu değil (https://docs.docker.com/engine/install/)"
  docker compose version >/dev/null 2>&1 || die "'docker compose' (v2) gerekli"
}

prepare_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$HERE/env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Ayar dosyası oluşturuldu: $ENV_FILE"
  fi
  setv FUTBOL_DB_PASSWORD "$(pw)"
  setv FUTBOL_REDIS_PASSWORD "$(pw)"
  setv MI_SECRET_KEK "$(rand)"
  setv MI_LICENSE_PEPPER "$(rand)"
  setv MI_METRICS_TOKEN "$(pw)"
  chmod 600 "$ENV_FILE"
}

preflight() {
  local port prefix
  port="$(get FUTBOL_PORT)"; prefix="$(get FUTBOL_SUBNET_PREFIX)"
  if command -v ss >/dev/null && ss -ltn "sport = :$port" | grep -q LISTEN; then
    docker ps --format '{{.Names}} {{.Ports}}' | grep -q "^futbol-web.*:$port->" \
      || die "127.0.0.1:$port başka bir program tarafından kullanılıyor; .env'de FUTBOL_PORT değiştirin"
  fi
  for n in $(docker network ls -q); do
    name="$(docker network inspect -f '{{.Name}}' "$n")"
    [ "$name" = "futbol_futbol" ] && continue
    if docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$n" | grep -q "^${prefix}\.\| ${prefix}\."; then
      die "${prefix}.0/24 alt ağı '$name' ağında kullanılıyor; .env'de FUTBOL_SUBNET_PREFIX değiştirin"
    fi
  done
}

wait_healthy() {
  echo -n "API hazır olana kadar bekleniyor"
  for _ in $(seq 1 90); do
    if [ "$(docker inspect -f '{{.State.Health.Status}}' futbol-api-1 2>/dev/null)" = "healthy" ]; then echo " ✓"; return 0; fi
    echo -n "."; sleep 2
  done
  echo; dc logs --tail 50 api; die "API sağlıklı duruma geçmedi"
}

psql_q() { dc exec -T postgres psql -U futbol -d futbol -tAc "$1"; }

case "${1:-}" in
  kur)
    need_docker; prepare_env; preflight
    first=0; docker volume inspect futbol_pgdata >/dev/null 2>&1 || first=1
    # FUTBOL_NO_BUILD=1: imajlar önceden derlendiyse (ör. CI) derlemeyi atla.
    [ "${FUTBOL_NO_BUILD:-0}" = 1 ] || dc build
    dc up -d
    wait_healthy
    if [ "$first" = 1 ]; then
      # İlk kurulum: kapalı önizleme. Yasal metinler (M-G4) ve e-posta (M-G6) hazır olana kadar yeni
      # üye kaydı kapalı; yönetim panelinden (Özellik Bayrakları) açılır.
      psql_q "UPDATE feature_flags SET enabled = false, message = 'Site önizleme aşamasında; üye kaydı yakında açılacak.', updated_at = now() WHERE key = 'registration_open'" >/dev/null
      echo "İlk kurulum: üye kaydı kapalı (önizleme)."
    fi
    port="$(get FUTBOL_PORT)"
    code=000
    for _ in $(seq 1 60); do
      code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/giris" || true)"
      [ "$code" = 200 ] && break; sleep 1
    done
    echo "Uygulama: http://127.0.0.1:$port (sunucu içi) → yanıt $code"
    echo "Sıradaki: web sunucusu ayarı + sertifika (docs/vds-kurulum.md §4), sonra:"
    echo "  $0 yonetici eposta@adres \"Ad Soyad\""
    ;;
  durum)
    need_docker
    dc ps
    echo; echo "Son yedekler:"
    psql_q "SELECT created_at::timestamp(0), status, coalesce(verify_ok::text,'-'), file_name FROM backups ORDER BY id DESC LIMIT 3" || true
    echo; echo "Şema sürümü: $(psql_q 'SELECT version_num FROM alembic_version' || echo '?')"
    ;;
  yonetici)
    [ $# -ge 3 ] || die "kullanım: $0 yonetici EPOSTA \"Ad Soyad\""
    dc run --rm api mi-admin bootstrap --email "$2" --name "$3"
    ;;
  yedek)
    dc exec -T worker mi-admin backup
    ;;
  guncelle)
    need_docker
    git -C "$ROOT" pull --ff-only
    dc exec -T worker mi-admin backup || die "Güncelleme öncesi yedek alınamadı; güncelleme durduruldu"
    dc build
    dc up -d
    wait_healthy
    ;;
  loglar)
    dc logs --tail 200 -f ${2:-}
    ;;
  durdur)
    dc stop
    ;;
  *)
    sed -n '2,13p' "$0"; exit 1
    ;;
esac
