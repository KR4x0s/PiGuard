#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
echo 'Activating the evaluated, alert-only compact forest release.'
echo 'This preserves alert state and does not change client DNS or Pi-hole blocking rules.'
exec sudo bash scripts/install_pi.sh \
  releases/final-001 \
  fc4f50f35b2f70d976cb10036e0eb6dff2253f5ef54b5c21d685683b33cf8b21
