#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
echo 'Activating an experimental, alert-only compact forest. Final acceptance is still pending.'
echo 'This does not change the Mac DNS or Pi-hole blocking policy.'
exec sudo bash scripts/install_pi.sh \
  runs/2026-10-25-baseline/candidates/compact_random_forest \
  6ebcc1e988478b8e843531b73a61b2b3a0bbc35581be4e8f1ef887ff1f9bb58b \
  --experimental
