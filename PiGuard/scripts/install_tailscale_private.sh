#!/usr/bin/env bash
# Install Tailscale from its signed Debian Trixie repository. Does not enroll or publish the Pi.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 2; fi
. /etc/os-release
if [[ ${ID:-} != debian || ${VERSION_CODENAME:-} != trixie ]]; then
  echo 'This installer is for Debian Trixie only.' >&2
  exit 2
fi
if command -v tailscale >/dev/null 2>&1; then
  tailscale version
  echo 'Tailscale already installed; enrollment and Serve remain separate.'
  exit 0
fi
install -d -m 0755 /usr/share/keyrings
key_tmp=$(mktemp)
list_tmp=$(mktemp)
trap 'rm -f "$key_tmp" "$list_tmp"' EXIT
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg -o "$key_tmp"
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list -o "$list_tmp"
if ! grep -q 'signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg' "$list_tmp"; then
  echo 'Unexpected Tailscale repository list' >&2
  exit 1
fi
install -m 0644 "$key_tmp" /usr/share/keyrings/tailscale-archive-keyring.gpg
install -m 0644 "$list_tmp" /etc/apt/sources.list.d/tailscale.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y tailscale
systemctl enable --now tailscaled
tailscale version
echo 'Installed but not enrolled. Configure restricted tailnet grants before enabling Serve.'
