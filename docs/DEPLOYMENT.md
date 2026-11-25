# Local deployment

1. Install Docker Engine and the Docker Compose plugin.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN`, `OPENAI_API_KEY`, `ADMIN_IDS` and a unique `POSTGRES_PASSWORD`. Do not commit `.env`.
4. Add feed URLs to `RSS_FEEDS` as a comma-separated list. MRC is enabled by default.
5. Run `docker compose up --build -d`.
6. Follow logs with `docker compose logs -f bot`.

The container applies Alembic migrations before starting the bot. PostgreSQL data is stored in the `postgres_data` volume.

## Importing the old SQLite archive

Make a protected backup of the latest SQLite file. After PostgreSQL is running and migrations are applied, run the importer from the project root:

```bash
python -m scripts.import_legacy_sqlite /path/to/storage.db --dry-run
python -m scripts.import_legacy_sqlite /path/to/storage.db
```

The importer opens the SQLite source using `mode=ro`. It preserves each legacy row ID and all available values. It is idempotent on `(source_id, external_id)`, so existing articles are skipped. Do not copy the database into the Git repository or Docker build context.

## Required environment

- `BOT_TOKEN`: Telegram bot token.
- `ADMIN_IDS`: comma-separated Telegram numeric user IDs authorized for `/load`.
- `DATABASE_URL`: `postgresql+asyncpg://...` connection URL.
- `OPENAI_API_KEY`: OpenAI project API key.
- `OPENAI_MODEL`: defaults to `gpt-4`.
- `POSTGRES_PASSWORD`: password for the local Postgres service.

GigaChat credentials are not needed for the default OpenAI deployment.
