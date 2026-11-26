# Telegram News Bot 2.0

A multi-source, AI-assisted editorial and Telegram publishing platform. The uploaded MRC implementation is the functional reference: its MRC AJAX listing endpoint, article URL format, HTML selectors, tag extraction, Russian transliteration and text normalization are retained in a dedicated source adapter. RSS feeds can be added through configuration without changing the application core.

## Product decisions

- **Telegram:** aiogram 3.x Bot API. Telethon is not required for the current MRC/RSS sources.
- **AI:** OpenAI GPT-6 Luna (`gpt-6-luna`) is the primary model. The bounded editorial agent uses allowlisted local tools; GigaChat remains an optional provider extension.
- **Sources:** multiple adapters, initially MRC and configurable RSS feeds.
- **Database:** PostgreSQL from the beginning, SQLAlchemy 2.x async and Alembic.
- **Runtime:** Python 3.13, HTTPX and Docker Compose.

## Start

1. Copy .env.example to .env.
2. Set BOT_TOKEN, OPENAI_API_KEY, ADMIN_IDS and a strong POSTGRES_PASSWORD.
3. Configure RSS_FEEDS as comma-separated feed URLs. MRC is enabled by default.
4. Set PUBLISH_CHANNEL_ID for the source-language channel and PUBLISH_CHANNEL_ID_EN for the English channel. Add the bot to both channels with permission to post.
5. Run docker compose up --build -d.
6. Follow logs with docker compose logs -f bot.

The container applies Alembic migrations before starting the bot. PostgreSQL data is persisted in the postgres_data volume. The bot performs an initial ingestion and repeats ingestion on the configured interval. /load triggers manual ingestion and /sources shows source health. Editorial and publishing commands are restricted to configured ADMIN_IDS.

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
