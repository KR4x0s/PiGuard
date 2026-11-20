#!/usr/bin/env bash
# Run on the Pi: sudo bash scripts/install_pi.sh CANDIDATE_DIR TRUSTED_MANIFEST_SHA256
set -euo pipefail
umask 022
if [[ $EUID -ne 0 || $# -lt 2 || $# -gt 3 ]]; then
  echo 'Usage: sudo bash scripts/install_pi.sh RELEASE_DIRECTORY TRUSTED_MANIFEST_SHA256 [--experimental]' >&2
  exit 2
fi
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
release=$(realpath -- "$1")
digest=$2
if [[ ! -f $release/metrics.json && ${3:-} != --experimental ]]; then
  echo 'Candidate is not finally evaluated. Use --experimental only for explicitly provisional alert-only testing.' >&2
  exit 2
fi
[[ $digest =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid manifest digest' >&2; exit 2; }
[[ $(sha256sum "$release/manifest.json" | cut -d' ' -f1) == "$digest" ]] || { echo 'Manifest mismatch' >&2; exit 1; }
[[ $(python3 --version) == 'Python 3.13.5' ]] || { echo 'Use the recorded Python 3.13.5 runtime' >&2; exit 1; }
[[ -f /etc/pihole/pihole-FTL.db ]] || { echo 'Expected Pi-hole query database is missing' >&2; exit 1; }
if ! command -v setfacl >/dev/null; then
  apt-get update
  apt-get install -y acl
fi
if ! id piguard >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/piguard --create-home --shell /usr/sbin/nologin piguard
fi
install -d -o root -g root -m 0755 /opt/piguard/releases /usr/local/libexec
install -d -o piguard -g piguard -m 0700 /var/lib/piguard
if [[ ! -f /var/lib/piguard/web-secret ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > /var/lib/piguard/web-secret
  chown piguard:piguard /var/lib/piguard/web-secret
  chmod 0600 /var/lib/piguard/web-secret
fi
release_id=$(date -u +%Y%m%dT%H%M%SZ)-${digest:0:12}
target=/opt/piguard/releases/$release_id
mkdir -m 0755 "$target"
cp -R "$source_root/piguard" "$source_root/deploy" "$source_root/scripts" "$target/"
cp "$source_root/piguard_dga_features.py" "$source_root/piguard_dga_inference.py" "$target/"
mkdir -m 0755 "$target/data"
cp "$source_root/data/public_suffix_list.dat" "$target/data/"
cp -R "$release" "$target/artifacts"
find "$target" -type d -exec chmod 0755 {} +
find "$target" -type f -exec chmod 0644 {} +
python3 -m venv "$target/.venv"
# Pin all exported packages, including transitive dependencies. Never deserialize before verification.
"$target/.venv/bin/python" -m pip install -r "$target/artifacts/requirements-pi.txt"
python3 - "$target" "$digest" <<'PY'
import json,sys
from pathlib import Path
target=Path(sys.argv[1])
(target/'deploy/active.json').write_text(json.dumps({
 'source_db':'/etc/pihole/pihole-FTL.db','state_db':'/var/lib/piguard/state.db',
 'release':str(target/'artifacts'),'manifest_sha256':sys.argv[2],'dns_server':'127.0.0.1'},indent=2))
PY
chown -R root:root "$target"
runuser -u piguard -- env PYTHONPATH="$target" PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  "$target/.venv/bin/python" "$target/piguard_dga_inference.py" --release "$target/artifacts" \
  --manifest-sha256 "$digest" example.com
install -m 0755 "$target/deploy/piguard-source-access" /usr/local/libexec/piguard-source-access
/usr/local/libexec/piguard-source-access
# Check the actual schema and read-only access before activating anything.
runuser -u piguard -- env PYTHONPATH="$target" PYTHONDONTWRITEBYTECODE=1 \
  "$target/.venv/bin/python" -c "from piguard.observer import source_open; db=source_open('/etc/pihole/pihole-FTL.db'); print('Query database schema/access verified'); db.close()"
previous=$(readlink -f /opt/piguard/current || true)
if [[ -n $previous && -d $previous ]]; then
  ln -sfn "$previous" /opt/piguard/previous
fi
ln -s "$target" /opt/piguard/current.next
mv -Tf /opt/piguard/current.next /opt/piguard/current
install -m 0644 "$target"/deploy/piguard-*.service "$target"/deploy/piguard-*.path "$target"/deploy/piguard-*.timer /etc/systemd/system/
systemctl daemon-reload
# The timer refreshes ACLs after database rotation. Watching the entire
# /etc/pihole directory triggers repeatedly during ordinary FTL activity and
# can hit systemd's start limit, leaving a failed path unit.
systemctl disable --now piguard-source-access.path 2>/dev/null || true
systemctl reset-failed piguard-source-access.path 2>/dev/null || true
systemctl enable --now piguard-source-access.timer
systemctl enable piguard-observer.service piguard-dashboard.service
systemctl restart piguard-observer.service piguard-dashboard.service
if ! "$target/.venv/bin/python" - <<'PY'
import time,urllib.request
for _ in range(30):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2) as r:
   if r.status==200:
    print('PiGuard observer and dashboard ready'); raise SystemExit(0)
 except OSError:
  pass
 time.sleep(3)
raise SystemExit(1)
PY
then
  echo 'Readiness failed; reverting activation' >&2
  if [[ -n $previous && -d $previous ]]; then
    ln -s "$previous" /opt/piguard/rollback.next
    mv -Tf /opt/piguard/rollback.next /opt/piguard/current
    systemctl restart piguard-observer piguard-dashboard
  else
    systemctl disable --now piguard-observer piguard-dashboard
  fi
  exit 1
fi
echo 'Installed in alert-only mode. This does not change client DNS or Pi-hole blocking rules.'
