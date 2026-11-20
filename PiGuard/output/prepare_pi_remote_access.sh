#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 2; fi
if [[ $(vcgencmd get_throttled) != throttled=0x0 ]]; then
  echo 'Pi reports throttling or historical power/temperature event; inspect hardware before installing another service.' >&2
  exit 1
fi
bash /home/krat0s/update_pi_gateway_bootstrap_retry.sh
bash /home/krat0s/PiGuard_Gateway_Dashboard_Final/scripts/install_tailscale_private.sh
# No DNS changes, subnet routes, exit-node role, or inbound tailnet access during enrollment.
tailscale up --accept-dns=false --accept-routes=false --shields-up
printf '\nPi enrolled with incoming tailnet connections blocked. Configure a restricted tailnet policy before enabling Serve.\n'
tailscale status
vcgencmd get_throttled
vcgencmd measure_temp
