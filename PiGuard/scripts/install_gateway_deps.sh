#!/usr/bin/env bash
# Debian package installation without starting default DNS/Tor services.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 022
[[ $EUID -eq 0 && $# -eq 0 ]] || { echo 'Usage: sudo bash scripts/install_gateway_deps.sh' >&2; exit 2; }
policy=/usr/sbin/policy-rc.d
[[ ! -e $policy && ! -L $policy ]] || {
  echo 'An existing service-start policy is present. Have the administrator install tor dnscrypt-proxy nftables dnsutils curl with service starts suppressed; the existing policy was preserved.' >&2
  exit 1
}
new_services=()
installed() { [[ $(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true) == 'install ok installed' ]]; }
if ! installed tor; then new_services+=(tor.service tor@default.service); fi
if ! installed dnscrypt-proxy; then new_services+=(dnscrypt-proxy.service dnscrypt-proxy.socket dnscrypt-proxy-resolvconf.service); fi
cleanup() {
  result=$?
  trap - EXIT
  # Only units belonging to newly installed packages; preserve existing instances.
  if [[ ${#new_services[@]} -gt 0 ]]; then
    systemctl disable --now "${new_services[@]}" 2>/dev/null || true
  fi
  if [[ $(sha256sum "$policy" 2>/dev/null | cut -d' ' -f1) == "$policy_digest" ]]; then
    rm -- "$policy"
  else
    echo 'Service-start policy changed concurrently; preserved for administrator review.' >&2
  fi
  exit "$result"
}
# noclobber refuses a concurrent creation instead of overwriting it.
(set -o noclobber; printf '#!/bin/sh\nexit 101\n' > "$policy")
chmod 0755 "$policy"
policy_digest=$(sha256sum "$policy" | cut -d' ' -f1)
trap cleanup EXIT
apt-get update
apt-get install -y --no-install-recommends tor dnscrypt-proxy nftables dnsutils curl
echo 'Dependencies installed. PiGuard gateway/Tor has not been activated.'
