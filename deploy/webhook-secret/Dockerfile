FROM alpine:3.22

RUN apk add --no-cache openssl

COPY deploy/webhook-secret/generate-secret.sh /usr/local/bin/generate-secret.sh
RUN chmod 0555 /usr/local/bin/generate-secret.sh

ENTRYPOINT ["/bin/sh", "/usr/local/bin/generate-secret.sh"]
