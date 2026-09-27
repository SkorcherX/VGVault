#!/bin/sh
set -e

# unRAID convention: run as PUID:PGID (default nobody:users = 99:100).
mkdir -p "$CONFIG_DIR"
chown -R "$PUID:$PGID" "$CONFIG_DIR"

exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups \
  uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
