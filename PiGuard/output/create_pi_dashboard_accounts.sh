#!/usr/bin/env bash
# Run from an interactive SSH session after the dashboard release is active.
set -euo pipefail
sudo -v
echo 'Create admin account: enter a password of at least 14 characters twice.'
sudo -u piguard env PYTHONPATH=/opt/piguard/current \
  /opt/piguard/current/.venv/bin/python -m piguard.accounts \
  --state /var/lib/piguard/state.db --username admin --role admin
echo 'Create viewer account: enter a separate password of at least 14 characters twice.'
sudo -u piguard env PYTHONPATH=/opt/piguard/current \
  /opt/piguard/current/.venv/bin/python -m piguard.accounts \
  --state /var/lib/piguard/state.db --username viewer --role viewer
echo 'Both accounts saved.'
