from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ip_tls_compose_keeps_private_key_out_of_bot_container():
    compose = (ROOT / "docker-compose.ip-tls.yml").read_text(encoding="utf-8")

    assert '443:443' in compose
    assert "WEBHOOK_CERTIFICATE_PATH:" in compose
    assert "webhook_public_cert:/run/webhook-certificate:ro" in compose
    assert "webhook_private_key:/etc/nginx/certs/private:ro" in compose
    assert "webhook_private_key:/run/webhook-certificate" not in compose


def test_ip_tls_proxy_uses_tls_and_dynamic_compose_dns():
    nginx = (ROOT / "deploy/ip-tls/nginx.conf").read_text(encoding="utf-8")

    assert "listen 443 ssl;" in nginx
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in nginx
    assert "server bot:8080 resolve;" in nginx
    assert "location = /telegram/webhook" in nginx


def test_certificate_script_sets_ip_common_name_and_subject_alt_name():
    script = (ROOT / "deploy/ip-tls/generate-certificate.sh").read_text(encoding="utf-8")

    assert '"/CN=$WEBHOOK_PUBLIC_IP"' in script
    assert '"subjectAltName=IP:$WEBHOOK_PUBLIC_IP"' in script
    assert 'chmod 600 "$PRIVATE_KEY"' in script



def test_webhook_secret_is_generated_once_and_shared_read_only_with_bot():
    compose = (ROOT / "docker-compose.webhook.yml").read_text(encoding="utf-8")
    generator = (ROOT / "deploy/webhook-secret/generate-secret.sh").read_text(encoding="utf-8")

    assert "webhook_secret:/run/secrets" in compose
    assert "webhook_secret:/run/secrets:ro" in compose
    assert "WEBHOOK_SECRET_TOKEN_FILE: /run/secrets/webhook_token" in compose
    assert "service_completed_successfully" in compose
    assert 'openssl rand -hex 32' in generator
    assert 'if [ ! -s "$SECRET_FILE" ]' in generator
    assert 'chmod 0444' in generator


def test_ip_tls_compose_keeps_secret_file_available_to_bot():
    compose = (ROOT / "docker-compose.ip-tls.yml").read_text(encoding="utf-8")

    assert "webhook_secret:/run/secrets:ro" in compose
    assert "WEBHOOK_SECRET_TOKEN_FILE: /run/secrets/webhook_token" in compose
