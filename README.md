# Telegram News Bot 2.0

A multi-source, AI-assisted editorial and Telegram publishing platform. The uploaded MRC implementation is the functional reference: its MRC AJAX listing endpoint, article URL format, HTML selectors, tag extraction, Russian transliteration and text normalization are retained in a dedicated source adapter. RSS feeds can be added through configuration without changing the application core.

## Product decisions

- **Telegram:** aiogram 3.x Bot API. Telethon is not required for the current MRC/RSS sources.
- **AI:** OpenAI GPT-6 Luna (`gpt-6-luna`) is the primary model. The bounded editorial agent uses allowlisted local tools; GigaChat remains an optional provider extension.
- **Sources:** multiple adapters, initially MRC and configurable RSS feeds.
- **Database:** PostgreSQL from the beginning, SQLAlchemy 2.x async and Alembic.
- **Runtime:** Python 3.13, HTTPX and Docker Compose.

## PostgreSQL connection pool

The async SQLAlchemy pool is configured per bot process. Defaults are:

- `DB_POOL_SIZE=5` — persistent connections retained by the process;
- `DB_MAX_OVERFLOW=5` — temporary connections allowed above the base pool;
- `DB_POOL_TIMEOUT_SECONDS=30` — maximum wait for a connection before failing;
- `DB_POOL_RECYCLE_SECONDS=1800` — recycle connections after 30 minutes;
- `pool_pre_ping=True` — validate pooled connections before reuse.

The SQLAlchemy pool budget is `DB_POOL_SIZE + DB_MAX_OVERFLOW` per process (10 with defaults). During ingestion, the distributed advisory lock also uses one transient, unpooled PostgreSQL connection per application instance attempting the lock. Multiply the pool budget plus this transient connection by the maximum number of concurrently running bot processes, then reserve capacity for Alembic, administration, monitoring and other services. Keep the sum below PostgreSQL's `max_connections` with operational headroom. Do not increase pool limits without checking the database connection budget and observed pool pressure.

Startup logs report configured pool capacity. Pool overflow transitions and invalidated connections are logged without connection strings, SQL, parameters or article content. A sustained overflow warning is a signal to inspect query duration and concurrency before raising limits.

## FSM storage and Redis

The default `FSM_STORAGE=memory` keeps the existing single-instance deployment unchanged. Memory storage is intentionally retained as the zero-dependency default for local/single-replica operation. To enable persistent shared FSM state on one instance for validation, use the Redis overlay:

    docker compose -f docker-compose.yml -f docker-compose.redis.yml up --build -d

The overlay starts Redis with AOF persistence and a healthcheck, configures `FSM_STORAGE=redis`, and waits for Redis before starting the bot. Redis state and data records use a bot-scoped key prefix and configurable 24-hour TTLs (`FSM_KEY_PREFIX`, `FSM_STATE_TTL_SECONDS`, `FSM_DATA_TTL_SECONDS`). For an external Redis deployment, set `FSM_STORAGE=redis` and `REDIS_URL` directly.

Redis-backed FSM is a prerequisite for multi-instance operation, not the complete scaling switch by itself. Multiple replicas also require webhook-based Telegram ingress (long polling is single-consumer), distributed scheduling, and coordinated worker ownership; those are subsequent Phase 4E steps. Do not scale the bot service until those steps are complete.

## Start

1. Copy .env.example to .env.
2. Set BOT_TOKEN, OPENAI_API_KEY, ADMIN_IDS and a strong POSTGRES_PASSWORD.
3. Configure RSS_FEEDS as comma-separated feed URLs. MRC is enabled by default.
4. Set PUBLISH_CHANNEL_ID for the source-language channel and PUBLISH_CHANNEL_ID_EN for the English channel. Add the bot to both channels with permission to post.
5. Start PostgreSQL with `docker compose up -d db`.
6. Apply schema migrations explicitly with `docker compose --profile migration run --rm migrate`.
7. Start the bot with `docker compose up --build -d bot`.
8. Follow logs with `docker compose logs -f bot`.

PostgreSQL data is persisted in the postgres_data volume. The bot begins Telegram polling after required dependency checks; initial ingestion runs in the background and repeats on the configured interval. /load triggers manual ingestion and /sources shows source health. Editorial and publishing commands are restricted to configured ADMIN_IDS.

## Deployment and startup

Database schema changes are an explicit deployment operation; the bot container never runs Alembic automatically.

1. Copy `.env.example` to `.env` and configure the required secrets and database settings.
2. Start PostgreSQL: `docker compose up -d db`.
3. Apply migrations as a separate deployment step: `docker compose --profile migration run --rm migrate`.
4. Start the bot: `docker compose up --build -d bot`.
5. Check readiness and logs: `docker compose ps` and `docker compose logs -f bot`.

The migration service is opt-in under the `migration` profile. The bot service does not depend on it and cannot mutate the schema during an ordinary restart. Run the migration step once for each deployment before starting application instances.

At startup the bot verifies PostgreSQL with `SELECT 1` and verifies the configured Telegram token with `getMe`. The container healthcheck repeats these core dependency checks. Optional source ingestion is scheduled immediately in the background and then runs at `INGESTION_INTERVAL_MINUTES`; it does not delay Telegram polling. A source outage therefore affects ingestion telemetry, not the bot's ability to accept Telegram updates. The OpenAI provider is initialized for use by editorial actions and is not a startup readiness dependency.

## Distributed ingestion coordination

Every application instance may register the same ingestion schedule, but the ingestion service acquires a PostgreSQL session-level advisory lock before doing any work. The lock is held on a dedicated database connection for the complete run and is released in a `finally` block; if the process or connection disappears, PostgreSQL releases the session lock. A replica that cannot acquire the lock skips the scheduled run. Manual `/load` and the control-deck feed scan use the same guarded service, so they cannot overlap a scheduled run on another instance.

The advisory lock coordinates ingestion only. It does not elect Telegram update consumers: multi-instance Telegram delivery still requires webhook ingress rather than multiple long-polling consumers. The single-instance polling deployment remains unchanged.

## Multi-instance webhook deployment

Polling remains the default and is intended for the existing single-instance setup. Do not scale a polling bot: Telegram permits either long polling or a webhook for a bot, not both, and long polling is a single-consumer update transport.

For a multi-instance deployment, configure a public HTTPS origin in the untracked `.env` file:

    WEBHOOK_BASE_URL=https://bot.example.com

The webhook Compose overlay creates a 256-bit random token on first start and stores it in the persistent `webhook_secret` Docker volume. Bot containers mount that volume read-only and load the token through `WEBHOOK_SECRET_TOKEN_FILE`. Leave `WEBHOOK_SECRET_TOKEN` blank to use the generated value. Existing deployments may continue setting `WEBHOOK_SECRET_TOKEN` directly; that value takes precedence over the file. Do not remove the `webhook_secret` volume during ordinary redeployments. Terminate TLS at a trusted reverse proxy/load balancer and route `/telegram/webhook` to port 8080 on the bot service. The bot binds internally to `0.0.0.0:8080`; the webhook handler verifies Telegram's `X-Telegram-Bot-Api-Secret-Token` header. Keep the bot containers private behind the proxy and restrict direct access to their webhook port.

After PR #9 (Redis FSM), PR #10 (PostgreSQL advisory lock), and this webhook PR are merged, apply migrations once:

    docker compose --profile migration run --rm migrate

Then start a Redis-backed webhook deployment:

    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml up --build -d --scale bot=3

All replicas share Redis FSM state and PostgreSQL. Their scheduled/manual ingestion attempts are serialized by the PostgreSQL advisory lock. The default `docker compose up` command still uses one polling instance and in-memory FSM. This scaling path does not change approval or publication semantics.

## Dedicated ingestion worker

For a scaled webhook deployment, the optional worker overlay moves APScheduler out of the Telegram bot replicas. The bot service receives updates and handles editorial workflows; the dedicated worker owns scheduled ingestion. The worker does not require a Telegram token, Redis FSM, or an AI provider key. It uses PostgreSQL advisory locking so multiple worker replicas can be run for availability without overlapping ingestion jobs.

Use all four overlays for the recommended multi-instance layout:

    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml -f docker-compose.worker.yml up --build -d --scale bot=3 --scale worker=1

The existing single-instance deployment is unchanged: `INGESTION_SCHEDULER_ENABLED=true` by default, so the bot continues to schedule ingestion in-process. The worker overlay disables that scheduler only on bot replicas and starts the separate worker service. To run multiple worker replicas, increase `--scale worker`; PostgreSQL advisory locks serialize their ingestion attempts.

The database connection budget now applies to every bot and worker process. Include each process's configured SQLAlchemy pool plus one transient advisory-lock connection during ingestion, and reserve headroom for migrations and operations.

## Ingestion quality

Transient network errors, HTTP 429 and HTTP 5xx responses are retried with bounded exponential backoff. A shared request limiter spaces requests across adapters, and MRC article concurrency is configurable.

Each source has a latest health state and an append-only run history. /sources shows the latest status, last attempt, fetched count, consecutive failures, duration and warnings.

Stored URLs are canonicalized by removing known tracking parameters, fragments, default ports and the www prefix. Content hashes ignore case and whitespace differences. Cross-source duplicate candidates are recorded for editorial review using canonical URL, content hash and title similarity. **The bot does not automatically merge, suppress or delete duplicate articles.**

## Editorial AI workflow

Use /drafts to see newly discovered articles waiting for an AI draft, then run /draft ARTICLE_UUID. The AI generates a structured editorial package containing a topic classification, concise summary, key points, named entities, important numeric facts, and Telegram and brief variants.

The pipeline stores provider/model, prompt version, validation results, model tool-call trace, attempt count, duration and token usage. It checks the summary word limit, whether output numeric values occur in the source, whether extracted entities occur in the source, whether both variants exist, and whether the source link is valid.

These automated checks are **source-consistency checks, not independent fact-checking**. They cannot establish whether the article itself is true. AI output is always saved as NEEDS_REVIEW; generation never approves or publishes.

## Button-driven Telegram control deck

Use /start to open the 🛰️ **NEWS OPS control deck**. The inline workflow is:

1. **Incoming articles → Generate AI draft** — select a discovered story and start editorial generation.
2. **RU review → Open review** — inspect the Telegram/brief variants and validation notes; edit copy from the **Edit copy** button by sending replacement text, or approve, reject, or regenerate with inline controls.
3. **After RU approval** — choose **Preview RU channel** to inspect the exact final post, then **Confirm RU publish** to send it. Or choose **Translate to English** to create an independently reviewable translation.
4. **EN review → Open review** — edit, approve, reject, or re-translate independently. After EN approval, preview and explicitly confirm publication to the English channel.
5. **Audit log** — inspect the append-only action history directly from each review/approval card.

Geek-style icons identify the stages (🛰️ control deck, 🧠 AI generation, 🧪 review, ✅ approval, 🌐 translation, 📡 source telemetry, 🚀 publishing). A publish action is only offered after the matching language version is approved. The confirmation callback is bound to the exact approved output shown in the preview; the existing SENDING/UNKNOWN reservation continues to prevent automatic duplicate sends. Slash commands remain available as fallback, but normal operation does not require article UUIDs or editorial slash commands.

## Human moderation

- /review lists source-language drafts awaiting moderation; /review en lists English translations; /review ARTICLE_UUID [ru|en] opens the selected language preview and moderation actions.
- Editors can edit the Telegram variant with /edit ARTICLE_UUID replacement text. Input is treated as plain text and safely HTML-escaped for Telegram.
- /regenerate ARTICLE_UUID produces a replacement draft. The former review draft is marked SUPERSEDED only after the replacement succeeds.
- /approve ARTICLE_UUID approves the latest draft only when all error-level validation checks pass. Non-blocking validation warnings remain visible.
- /reject ARTICLE_UUID [REASON] rejects the draft and records the reason.
- /history ARTICLE_UUID displays the append-only audit trail, including actor Telegram IDs, timestamps and action details.
- /translate ARTICLE_UUID en creates an English translation from the approved Russian editorial package. The English title, summary, key points and channel variants are stored as a separate output.
- /edit ARTICLE_UUID en TEXT edits the English Telegram variant. /approve ARTICLE_UUID en and /reject ARTICLE_UUID en [REASON] manage the English draft independently from the Russian approval.

All moderation actions are restricted to configured ADMIN_IDS. A moderation decision is never made by the AI.

## Explicit publishing and duplicate-send protection

Set PUBLISH_CHANNEL_ID and PUBLISH_CHANNEL_ID_EN and grant the bot permission to post to each destination. An administrator must run /publish ARTICLE_UUID for the source-language post or /publish ARTICLE_UUID en for the English post after separately reviewing and approving each version. The publishing service checks the corresponding approved output and blocking validation results before reserving a send.

Each publication row records its exact AI output and language. The database enforces one publication reservation per article and destination channel. A reservation is persisted as SENDING before calling Telegram. A successful response changes the article and publication to PUBLISHED and records the Telegram message ID. If the Telegram request fails or its outcome is ambiguous, the reservation becomes UNKNOWN (or remains SENDING if the process exits before it can update the database). These states are intentionally not retried automatically: check the channel manually before any operational intervention. This conservative behavior avoids duplicate posts when Telegram accepted a message but the client lost the response.

A message send and a database commit cannot be made one atomic transaction across Telegram and PostgreSQL. The SENDING/UNKNOWN guard therefore favors at-most-once behavior over automatic recovery. Every publish request and outcome is included in /history.

## AI providers

AI_PROVIDER=openai is the default and OPENAI_MODEL=gpt-6-luna selects GPT-6 Luna. The OpenAI adapter uses Chat Completions function calling with `reasoning_effort=none`, as required for GPT-6 Luna, and omits the unsupported custom temperature setting. GPT-6 requests use `max_completion_tokens`; legacy model overrides continue to use their compatible token-limit parameter. GigaChat credentials are not required for the default deployment; GigaChat remains a separately installable provider extension.

For a legacy non-GPT-6 model override, `OPENAI_TEMPERATURE` is still available; it is not sent to GPT-6 Luna. AI resource controls are configurable through AI_REQUEST_TIMEOUT_SECONDS, AI_RUN_TIMEOUT_SECONDS, AI_RETRY_ATTEMPTS, AI_RETRY_BASE_DELAY_SECONDS, AI_MAX_TOOL_ROUNDS, AI_MAX_INPUT_CHARS, AI_MAX_COMPLETION_TOKENS_PER_REQUEST, AI_MAX_COMPLETION_TOKENS_PER_ARTICLE and AI_SUMMARY_MAX_WORDS.

## Legacy SQLite archive

The latest supplied SQLite file has a motor table with 646 records and these columns: id, news_id, title, link, status and date. The database itself is deliberately excluded from Git and Docker builds. Keep a protected backup and use:

    python -m scripts.import_legacy_sqlite /path/to/storage.db --dry-run
    python -m scripts.import_legacy_sqlite /path/to/storage.db

The importer reads the source database in read-only mode, preserves the original row ID and all available legacy fields, and is idempotent. Legacy Send maps to SUMMARIZED because it meant the draft was sent to the moderation chat, not published. Del and Can't del - more 48H map to REJECTED; empty statuses map to DISCOVERED.

## AI model benchmark

See [docs/benchmarking.md](docs/benchmarking.md) for the isolated model-comparison runner, dataset format, cost accounting and human scoring workflow. The benchmark does not publish to Telegram.

## Development

    pip install -e '.[dev]'
    ruff check .
    pytest
    alembic upgrade head
    python -m compileall -q app migrations scripts

CI runs Ruff, pytest, compileall and the Alembic upgrade against a disposable PostgreSQL service. Editorial and moderation/publishing integration tests run against that PostgreSQL database when DATABASE_URL is set.

## Security

Never commit .env, bot tokens, API keys, production database files or runtime data. The uploaded development archive contained credential-like values; rotate any that were real before deployment. TLS certificate verification stays enabled.


## IP-only Docker webhook deployment

Telegram supports a self-signed webhook certificate whose common name is the server IP address. This deployment keeps TLS termination inside Docker Compose and does not require a registered domain or a host-installed reverse proxy. Telegram must receive the public PEM certificate in the `certificate` parameter when `setWebhook` is called; the application uploads it on each webhook startup. The private key remains in a separate Docker volume mounted only into Nginx.

This is an opt-in deployment overlay. The ordinary `docker compose up -d bot` deployment remains single-instance polling with in-memory FSM. Keep `BOT_TRANSPORT=polling` in the root `.env`; the IP-TLS overlay overrides transport only for its webhook deployment. Do not run polling and webhook stacks for the same bot at the same time.

### Configure the VPS

1. Allow inbound TCP 443 in the DigitalOcean Cloud Firewall and UFW. Keep SSH access open. Do not expose ports 8080, 5432 or 6379.
2. Set `WEBHOOK_PUBLIC_IP` in the untracked `.env` file to the Droplet's public IPv4 address.
3. Leave `WEBHOOK_SECRET_TOKEN` blank to let Compose generate and persist it automatically. Set it only if you intentionally want to supply an existing token.
4. Keep `DROP_PENDING_UPDATES=false`. Do not put certificate or private-key files in the repository. Preserve the `webhook_secret` Docker volume across redeployments.

Example values:

    BOT_TRANSPORT=polling
    WEBHOOK_PUBLIC_IP=203.0.113.10
    WEBHOOK_SECRET_TOKEN=
    WEBHOOK_CERT_REGENERATE=false

### Deploy

Run these commands from the repository directory. The first command starts PostgreSQL; the second applies migrations once. The final command creates the IP-bound certificate, starts the TLS proxy, and launches the webhook replicas and dedicated worker.

    docker compose up -d db
    docker compose --profile migration run --rm migrate

    docker compose \
      -f docker-compose.yml \
      -f docker-compose.redis.yml \
      -f docker-compose.webhook.yml \
      -f docker-compose.worker.yml \
      -f docker-compose.ip-tls.yml \
      up --build -d --scale bot=3 --scale worker=1

The public endpoint is `https://<WEBHOOK_PUBLIC_IP>/telegram/webhook`. Only Nginx publishes port 443. It proxies to the bot containers over the private Compose network and dynamically resolves the scaled `bot` service through Docker DNS. The public certificate is mounted read-only into the bot containers for Telegram's certificate upload; the private key is never mounted into a bot container.

Check the services and logs:

    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml -f docker-compose.worker.yml -f docker-compose.ip-tls.yml ps
    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml -f docker-compose.worker.yml -f docker-compose.ip-tls.yml logs --tail=100 proxy bot

Verify the webhook using the Bot API's `getWebhookInfo` method. Confirm the URL matches the public IP, `has_custom_certificate` is true, and `last_error_message` is empty. Do not paste the bot token into shell history or shared logs.

### Certificate replacement

The certificate is stored in Docker volumes. It is generated once and checked against `WEBHOOK_PUBLIC_IP` on subsequent deployments. If the Droplet IP changes or the certificate needs replacement, stop the webhook stack, set `WEBHOOK_CERT_REGENERATE=true` in `.env`, and run the certificate service with the same Compose files:

    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml -f docker-compose.worker.yml -f docker-compose.ip-tls.yml stop proxy bot
    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml -f docker-compose.worker.yml -f docker-compose.ip-tls.yml run --rm certgen

Then set `WEBHOOK_CERT_REGENERATE=false` and recreate the proxy and bot services. Each bot registers the current public certificate with Telegram during startup.

### Roll back to single-instance polling

Stop the complete webhook stack before starting polling. Do not use `down -v`, because that would delete PostgreSQL and Redis data.

    docker compose -f docker-compose.yml -f docker-compose.redis.yml -f docker-compose.webhook.yml -f docker-compose.worker.yml -f docker-compose.ip-tls.yml down
    docker compose up --build -d bot

The base Compose configuration and `.env` retain polling and memory FSM defaults. This rollback does not alter article data or publishing approval state.
