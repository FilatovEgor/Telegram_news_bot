#!/bin/sh
set -eu

SECRET_FILE="${WEBHOOK_SECRET_FILE:-/run/secrets/webhook_token}"
SECRET_DIR="$(dirname "$SECRET_FILE")"
mkdir -p "$SECRET_DIR"

if [ ! -s "$SECRET_FILE" ]; then
    umask 077
    TEMP_FILE="${SECRET_FILE}.tmp"
    trap 'rm -f "$TEMP_FILE"' EXIT HUP INT TERM
    openssl rand -hex 32 > "$TEMP_FILE"
    chmod 0444 "$TEMP_FILE"
    mv "$TEMP_FILE" "$SECRET_FILE"
    trap - EXIT HUP INT TERM
fi

chmod 0444 "$SECRET_FILE"
