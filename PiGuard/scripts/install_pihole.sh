#!/usr/bin/env bash
# Interactive first installation; run in the owner's terminal so sudo stays private.
set -euo pipefail
umask 077

if [ "$(uname -s)" != Linux ] || [ ! -r /proc/device-tree/model ]; then
  echo 'Run this on the Raspberry Pi.' >&2
  exit 2
fi
if ! tr -d '\0' </proc/device-tree/model | grep -q Raspberry; then
  echo 'This installer is intended for the Raspberry Pi.' >&2
  exit 2
fi
if [ ! -t 0 ] || [ ! -t 1 ]; then
  echo 'Use an interactive terminal (ssh -t), because sudo and Pi-hole need input.' >&2
  exit 2
fi
if command -v pihole >/dev/null 2>&1; then
  echo 'Pi-hole is already installed. Inspect its status before repair or reconfiguration.'
  pihole version
  exit 0
fi

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$project_dir/evidence"
run_id=$(date -u +%Y%m%dT%H%M%SZ)
bash "$project_dir/scripts/preflight.sh" > "$project_dir/evidence/preflight-$run_id.txt"

echo 'Installing Pi-hole and DNS diagnostic tools.'
echo 'Enter your Pi password at the sudo prompt; it will not be recorded by this script.'
echo 'Use wlan0, Cloudflare upstream, the default blocklist, and query logging.'
echo 'Keep DHCP on the router. Reserve the Pi LAN address before broader client enrollment.'
sudo -v
sudo apt-get update
sudo apt-get install -y curl ca-certificates dnsutils

installer=$(mktemp)
trap 'rm -f -- "$installer"' EXIT
curl --fail --show-error --location --retry 2 --connect-timeout 15 --max-time 180 \
  https://install.pi-hole.net --output "$installer"
bash -n "$installer"
sha256sum "$installer" > "$project_dir/evidence/installer-$run_id.sha256"
# Keep the upstream interactive wizard and its credentials in the user's terminal.
sudo bash -c 'umask 022; exec bash "$1"' bash "$installer"

echo 'Checking local DNS resolution...'
python3 "$project_dir/scripts/check_dns.py" 127.0.0.1 \
  --output "$project_dir/evidence/dns-local-$run_id.json"
echo 'Installation and local resolution checks completed. Client blocking tests are next.'
