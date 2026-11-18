#!/usr/bin/env bash
# Kurulum öncesi ön kontrol — YALNIZCA OKUR, hiçbir şeyi değiştirmez.
# Kullanım (sunucuda):  bash deploy/vds/kontrol.sh
# Çıktıyı olduğu gibi gönderin; web sunucusu türüne ve boş kaynaklara göre kurulum netleşir.
set -u
DOMAIN="${FUTBOL_DOMAIN:-futbol.canarslan.net.tr}"
PORT="${FUTBOL_PORT:-3080}"
PREFIX="${FUTBOL_SUBNET_PREFIX:-172.30.88}"
say() { printf '\n== %s\n' "$1"; }

say "İşletim sistemi"
(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -a
echo "Çekirdek: $(uname -r)  Mimari: $(uname -m)"

say "Kaynaklar"
echo "İşlemci çekirdeği: $(nproc 2>/dev/null)"
free -h 2>/dev/null | sed -n '1,2p'
df -h / /opt /var/lib/docker 2>/dev/null | awk 'NR==1 || !seen[$0]++'

say "Docker"
if command -v docker >/dev/null; then
  docker --version
  docker compose version 2>/dev/null || echo "UYARI: 'docker compose' (v2) yok"
  echo "Çalışan kapsayıcılar: $(docker ps -q 2>/dev/null | wc -l)"
  echo "Mevcut Docker ağları (alt ağ çakışması kontrolü):"
  for n in $(docker network ls -q 2>/dev/null); do
    docker network inspect -f '  {{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}' "$n" 2>/dev/null
  done
  if docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' $(docker network ls -q) 2>/dev/null | grep -q "^${PREFIX}\."; then
    echo "  ÇAKIŞMA: ${PREFIX}.0/24 başka bir ağda kullanılıyor → env'de FUTBOL_SUBNET_PREFIX değiştirin"
  else
    echo "  ${PREFIX}.0/24 boş görünüyor"
  fi
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^futbol-'; then echo "  Not: futbol projesine ait kapsayıcılar zaten var"; fi
else
  echo "Docker kurulu değil"
fi

say "Dinlenen portlar (80, 443, ${PORT})"
if command -v ss >/dev/null; then
  ss -ltnp 2>/dev/null | awk -v p=":${PORT}$" 'NR==1 || $4 ~ /:80$/ || $4 ~ /:443$/ || $4 ~ p'
else
  netstat -ltnp 2>/dev/null | grep -E ':(80|443|'"${PORT}"') '
fi

say "Web sunucusu / kontrol paneli"
for p in nginx apache2 httpd caddy litespeed lshttpd openresty traefik haproxy; do
  pgrep -x "$p" >/dev/null 2>&1 && echo "Çalışıyor: $p"
done
[ -d /usr/local/psa ] && echo "Panel: Plesk"
[ -d /usr/local/cpanel ] && echo "Panel: cPanel/WHM"
[ -d /www/server/panel ] && echo "Panel: aaPanel/BT"
[ -d /usr/local/CyberCP ] && echo "Panel: CyberPanel"
[ -d /etc/webmin ] && echo "Panel: Webmin/Virtualmin"
[ -d /usr/local/directadmin ] && echo "Panel: DirectAdmin"
[ -d /etc/nginx/sites-enabled ] && echo "nginx site dizini: /etc/nginx/sites-enabled ($(ls /etc/nginx/sites-enabled 2>/dev/null | wc -l) dosya)"
[ -d /etc/nginx/conf.d ] && echo "nginx conf.d: $(ls /etc/nginx/conf.d 2>/dev/null | wc -l) dosya"
[ -d /etc/apache2/sites-enabled ] && echo "Apache site dizini: /etc/apache2/sites-enabled"
command -v certbot >/dev/null && echo "certbot: $(certbot --version 2>&1)"

say "DNS"
echo "Sunucu adresleri: $(hostname -I 2>/dev/null)"
echo "${DOMAIN} → $(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
echo "canarslan.net.tr → $(getent ahostsv4 canarslan.net.tr 2>/dev/null | awk 'NR==1{print $1}' || true)"

say "Bitti (hiçbir şey değiştirilmedi)"
