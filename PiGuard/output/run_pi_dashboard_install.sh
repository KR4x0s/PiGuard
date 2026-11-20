#!/usr/bin/env bash
# Run on KREO from an interactive SSH session; sudo and account passwords stay in that terminal.
set -euo pipefail

cd /home/krat0s/PiGuard_ML_Dashboard_Final
sudo -v
sudo bash scripts/install_pi.sh releases/final-001 fc4f50f35b2f70d976cb10036e0eb6dff2253f5ef54b5c21d685683b33cf8b21

sudo -u piguard env PYTHONPATH=/opt/piguard/current \
  /opt/piguard/current/.venv/bin/python -m piguard.accounts \
  --state /var/lib/piguard/state.db --username admin --role admin
sudo -u piguard env PYTHONPATH=/opt/piguard/current \
  /opt/piguard/current/.venv/bin/python -m piguard.accounts \
  --state /var/lib/piguard/state.db --username viewer --role viewer

curl --fail --silent --show-error http://127.0.0.1:8080/healthz
printf '\nDashboard installation and account creation complete.\n'
