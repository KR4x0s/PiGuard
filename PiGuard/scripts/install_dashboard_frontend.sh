#!/usr/bin/env bash
# Run only after eth0 has 10.78.0.1/24 and the upgraded ML dashboard is healthy.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID -eq 0 ]] || { echo 'Run with sudo on the Pi' >&2; exit 2; }
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ -x /usr/sbin/nginx && -x /usr/bin/openssl ]] || { echo 'Install nginx and openssl first' >&2; exit 1; }
ip -4 -j address show eth0 | python3 -c 'import json,sys; a=json.load(sys.stdin); assert any(x.get("local")=="10.78.0.1" and x.get("prefixlen")==24 for i in a for x in i.get("addr_info",[]))' || { echo 'Configure eth0 as 10.78.0.1/24 first' >&2; exit 1; }
[[ -f /var/lib/piguard/web-secret ]] || { echo 'Upgrade PiGuard ML dashboard first' >&2; exit 1; }
install -d -o root -g root -m 0700 /etc/piguard-web /usr/local/lib/piguard-control
if [[ ! -f /etc/piguard-web/cert.pem ]]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
    -keyout /etc/piguard-web/key.pem -out /etc/piguard-web/cert.pem \
    -subj '/CN=PiGuard local' -addext 'subjectAltName=IP:10.78.0.1' >/dev/null 2>&1
  chmod 0600 /etc/piguard-web/key.pem
  chmod 0644 /etc/piguard-web/cert.pem
fi
install -m 0755 "$source_root/scripts/control_broker.py" /usr/local/lib/piguard-control/control_broker.py
install -m 0644 "$source_root/deploy/piguard-control.service" /etc/systemd/system/piguard-control.service
install -m 0644 "$source_root/deploy/piguard-nginx.conf" /etc/nginx/conf.d/piguard.conf
if [[ ! -f /etc/piguard-web/pihole.toml.before-dashboard ]]; then
  cp -p /etc/pihole/pihole.toml /etc/piguard-web/pihole.toml.before-dashboard
fi
had_default=0
restore_frontend() {
  systemctl disable --now nginx.service || true
  systemctl disable --now piguard-control.service || true
  rm -f /etc/nginx/conf.d/piguard.conf
  cp -p /etc/piguard-web/pihole.toml.before-dashboard /etc/pihole/pihole.toml
  for attempt in {1..20}; do
    if curl --fail --silent --max-time 2 http://127.0.0.1/admin/ >/dev/null; then break; fi
    sleep 1
  done
  if ! curl --fail --silent --max-time 2 http://127.0.0.1/admin/ >/dev/null; then
    systemctl restart pihole-FTL.service || true
  fi
  if [[ $had_default -eq 1 ]]; then
    ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
  fi
}
trap restore_frontend ERR
if [[ -L /etc/nginx/sites-enabled/default && $(realpath /etc/nginx/sites-enabled/default) == /etc/nginx/sites-available/default ]]; then
  had_default=1
  rm /etc/nginx/sites-enabled/default
fi
nginx -t
systemctl daemon-reload
systemctl enable --now piguard-control.service
pihole-FTL --config webserver.port '127.0.0.1:8081'
pihole-FTL --config webserver.paths.prefix '/pihole'
web_ready=0
for attempt in {1..30}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8081/admin/ >/dev/null; then
    web_ready=1
    break
  fi
  sleep 1
done
if [[ $web_ready -eq 0 ]]; then
  systemctl restart pihole-FTL.service
  for attempt in {1..30}; do
    if curl --fail --silent --max-time 2 http://127.0.0.1:8081/admin/ >/dev/null; then
      web_ready=1
      break
    fi
    sleep 1
  done
fi
[[ $web_ready -eq 1 ]] || { echo 'Pi-hole loopback web service did not become ready' >&2; false; }
systemctl enable --now nginx.service
curl --fail --silent --max-time 5 http://127.0.0.1:8080/login >/dev/null
trap - ERR
echo 'Local dashboard: https://10.78.0.1/ (self-signed certificate; verify fingerprint before trusting)'
openssl x509 -in /etc/piguard-web/cert.pem -noout -fingerprint -sha256
echo 'Create accounts with piguard.accounts --username NAME --role admin (or viewer); see DEPLOY_DASHBOARD.md'
echo 'Tailscale Serve target after private enrollment: http://127.0.0.1:8090'
