#!/bin/sh
set -eu

: "${WEBHOOK_PUBLIC_IP:?WEBHOOK_PUBLIC_IP must be set to the VPS public IPv4 address}"

PUBLIC_CERT=/public/telegram-webhook-public.pem
PRIVATE_KEY=/private/telegram-webhook-private.key

mkdir -p /public /private

if [ "${WEBHOOK_CERT_REGENERATE:-false}" != "true" ] && [ -s "$PUBLIC_CERT" ] && [ -s "$PRIVATE_KEY" ]; then
    if openssl x509 -in "$PUBLIC_CERT" -noout -checkip "$WEBHOOK_PUBLIC_IP" >/dev/null 2>&1; then
        echo "Existing webhook certificate matches $WEBHOOK_PUBLIC_IP"
        exit 0
    fi
    echo "Existing certificate does not match $WEBHOOK_PUBLIC_IP; set WEBHOOK_CERT_REGENERATE=true to replace it" >&2
    exit 1
fi

umask 077
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
    -keyout "$PRIVATE_KEY" \
    -out "$PUBLIC_CERT" \
    -subj "/CN=$WEBHOOK_PUBLIC_IP" \
    -addext "subjectAltName=IP:$WEBHOOK_PUBLIC_IP" \
    -addext "extendedKeyUsage=serverAuth"

chmod 600 "$PRIVATE_KEY"
chmod 644 "$PUBLIC_CERT"
openssl x509 -in "$PUBLIC_CERT" -noout -checkip "$WEBHOOK_PUBLIC_IP" >/dev/null

echo "Created self-signed webhook certificate for $WEBHOOK_PUBLIC_IP"
