# Telegram News Bot 2.0

A multi-source, AI-assisted editorial and Telegram publishing platform. The uploaded MRC implementation is the functional reference: its MRC AJAX listing endpoint, article URL format, HTML selectors, tag extraction, Russian transliteration and text normalization are retained in a dedicated source adapter. RSS feeds can be added through configuration without changing the application core.

## Product decisions

- **Telegram:** aiogram 3.x Bot API. Telethon is not required for the current MRC/RSS sources.
- **AI:** OpenAI GPT-4 is the primary model. The bounded editorial agent uses allowlisted local tools; GigaChat remains an optional provider extension.
- **Sources:** multiple adapters, initially MRC and configurable RSS feeds.
- **Database:** PostgreSQL from the beginning, SQLAlchemy 2.x async and Alembic.
- **Runtime:** Python 3.13, HTTPX and Docker Compose.

## Start

1. Copy `.env.example` to `.env`.
2. Set `BOT_TOKEN`, `OPENAI_API_KEY`, `ADMIN_IDS` and a strong `POSTGRES_PASSWORD`.
3. Configure `RSS_FEEDS` as comma-separated feed URLs. MRC is enabled by default.
4. Run `docker compose up --build -d`.
5. Follow logs with `docker compose logs -f bot`.

The container applies Alembic migrations before starting the bot. PostgreSQL data is persisted in the `postgres_data` volume. The bot performs an initial ingestion and repeats ingestion on the configured interval. `/load` triggers manual ingestion and is restricted to configured administrators.

## AI providers

`AI_PROVIDER=openai` is the default and `OPENAI_MODEL=gpt-4` preserves the requested GPT-4 integration. The agent may call only local validation and formatting tools; there is no AI tool that publishes to Telegram. Human approval remains mandatory. GigaChat credentials are not required for the default deployment; GigaChat remains a separately installable provider extension.

## Legacy SQLite archive

The latest supplied SQLite file has a `motor` table with 646 records and these columns: `id`, `news_id`, `title`, `link`, `status` and `date`. The database itself is deliberately excluded from Git and Docker builds. Keep a protected backup and use:

```bash
python -m scripts.import_legacy_sqlite /path/to/storage.db --dry-run
python -m scripts.import_legacy_sqlite /path/to/storage.db
```

The importer reads the source database in read-only mode, preserves the original row ID and all available legacy fields, and is idempotent. Legacy `Send` maps to `SUMMARIZED` because it meant the draft was sent to the moderation chat, not published. `Del` and `Can't del - more 48H` map to `REJECTED`; empty statuses map to `DISCOVERED`.

## Development

```bash
pip install -e '.[dev]'
ruff check .
pytest
python -m compileall -q app migrations scripts
```

## Security

Never commit `.env`, bot tokens, API keys, production database files or runtime data. The uploaded development archive contained credential-like values; rotate any that were real before deployment. TLS certificate verification stays enabled.
