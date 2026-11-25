# Telegram News Bot 2.0

Multi-source, AI-assisted news editorial and Telegram publishing platform. The updated MRC implementation supplied in the project ZIP is the functional reference. MRC and configurable RSS feeds are supported through source adapters.

## Decisions

- Telegram: aiogram 3.x Bot API. Telethon is deferred unless ingestion from Telegram user-account sessions becomes a requirement.
- AI: OpenAI GPT-4 is primary. A bounded tool-calling editorial agent uses allowlisted local tools and has no publishing tool. GigaChat remains an optional provider extension.
- Sources: MRC plus multiple configurable RSS feeds.
- Database: PostgreSQL, SQLAlchemy 2.x async, Alembic.
- Deployment: Docker Compose with a persistent PostgreSQL volume and environment-based configuration.

## Start

1. Copy `.env.example` to `.env`.
2. Set `BOT_TOKEN`, `OPENAI_API_KEY`, `ADMIN_IDS` and a strong `POSTGRES_PASSWORD`.
3. Configure one or more comma-separated feed URLs in `RSS_FEEDS` if required. MRC is enabled by default.
4. Start the stack: `docker compose up --build -d`.
5. Follow logs: `docker compose logs -f bot`.

The bot applies Alembic migrations before it starts. `/load` triggers ingestion for configured administrators; APScheduler runs periodic ingestion.

## Legacy database

The supplied ZIP contains a SQLite `motor` table with 646 rows and columns `id`, `news_id`, `title`, `link`, `status`, `date`. The SQLite file is deliberately not committed. Back it up outside Git and run the one-time importer after PostgreSQL is ready:

```bash
python scripts/import_legacy_sqlite.py /path/to/storage.db
```

Legacy `Send` maps to `SUMMARIZED` because the old application assigned it when the AI review draft was sent to the moderation chat, not when the channel post was published. `Del` maps to `REJECTED`. The original status and date are preserved in `legacy_status` and `legacy_date`.

## Development

```bash
pip install -e '.[dev]'
ruff check .
pytest
python -m compileall -q app migrations scripts
```

## Security

Never commit `.env`, tokens, API keys, local databases, database dumps or production exports. The uploaded archive contained credential-like values; revoke and rotate any values that were real. The example file contains placeholders only. HTTP TLS verification stays enabled.
