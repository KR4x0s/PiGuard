#!/usr/bin/env bash
# Correct public web asset permissions after the initial restrictive-umask install.
set -euo pipefail
if [ "$EUID" -ne 0 ]; then
  echo 'Run with sudo in your own terminal.' >&2
  exit 2
fi
if [ ! -f /var/www/html/admin/login.lp ]; then
  echo 'Expected Pi-hole login page is missing; inspect installation before changing permissions.' >&2
  exit 1
fi
for directory in /var/www /var/www/html /var/www/html/admin; do
  if [ -L "$directory" ]; then
    echo "Unexpected symlink: $directory; inspect manually." >&2
    exit 1
  fi
done
chmod 755 /var/www /var/www/html
# These are public web assets; leave Git metadata and all /etc/pihole files alone.
find /var/www/html/admin -name .git -prune -o -type d -exec chmod 755 {} +
find /var/www/html/admin -name .git -prune -o -type f -exec chmod a+r {} +
status=$(curl --silent --show-error --max-time 10 --output /dev/null \
  --write-out '%{http_code}' http://127.0.0.1/admin/login)
echo "Pi-hole login HTTP status: $status"
test "$status" = 200
