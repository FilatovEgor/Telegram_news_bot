# Telegram News Bot 2.0 — Phase 1 implementation plan

## Confirmed decisions

- **Sources:** multi-source from the start: MRC plus configurable RSS feeds, with a source-adapter interface for future providers.
- **AI:** OpenAI GPT-4 is the primary provider. A bounded tool-calling editorial agent may call only local allowlisted tools. GigaChat is reserved as an optional provider extension and is not required by the default deployment.
- **Database:** PostgreSQL from the beginning, with SQLAlchemy 2.x async and Alembic.
- **Telegram:** aiogram 3.x Bot API. Telethon is deferred until channel ingestion through a user account is required.
- **Deployment:** Docker Compose with persistent PostgreSQL storage and environment-based secrets.

## Phase 1 deliverables

1. Establish application layers for startup, Telegram, AI, sources, business services, persistence and scheduling.
2. Move secrets into environment configuration; do not commit `.env`, database files, tokens or credentials.
3. Preserve the uploaded MRC source semantics: AJAX listing URL, `/news/{slug}` paths, article title/body selectors, tag extraction, Russian transliteration and text normalization. Replace disabled TLS verification and repeated per-field downloads with one verified async fetch per article.
4. Add a configurable RSS adapter and multi-source registry.
5. Add PostgreSQL models and an Alembic initial migration for sources, articles, AI outputs, editorial actions, publications and admins.
6. Add an idempotent, read-only-source importer for the legacy SQLite `motor` table, retaining `id`, `news_id`, `title`, `link`, `status` and `date`.
7. Add the GPT-4 provider and a bounded agent with local validation/formatting tools. No agent tool may publish to Telegram; human approval remains mandatory.
8. Add admin-only `/load`, startup and scheduled source ingestion, Docker Compose and CI checks.

## Verified legacy database

The latest supplied `storage(1).db` has a valid SQLite integrity check and 646 rows in `motor`:

| Legacy status | Rows | New status |
|---|---:|---|
| empty / NULL | 470 | `DISCOVERED` |
| `Send` | 166 | `SUMMARIZED` |
| `Del` | 10 | `REJECTED` |

`Send` means the old bot sent an article to the moderation chat for review; it does **not** mean it was published. The importer retains the original row ID and old status/date fields. The DB file itself stays outside Git.

## Acceptance criteria

- Ruff, pytest and compile checks pass in CI.
- The app connects to PostgreSQL and starts aiogram polling with valid configuration.
- Manual and scheduled ingestion share one source registry.
- Re-discovered articles are idempotent by source + external ID.
- MRC fetches use normal TLS verification, timeouts and bounded concurrency.
- The SQLite importer reads source data in read-only mode and is safe to rerun.
- No `.env`, production secrets, SQLite DB, bytecode or runtime data is committed.

## Next phases

- **Phase 2:** source health, retries, per-source rate limits, URL canonicalization and cross-source duplicate detection.
- **Phase 3:** agentic classification, summarization, factual consistency checks, prompt/version tracking, cost controls and tool-call audit.
- **Phase 4:** editorial preview/edit/regenerate/approve/reject, audit trail and idempotent Telegram publishing.
- **Phase 5:** multiple channels, topic/language routing and optional Telethon source connector.
- **Phase 6:** observability, backups, restore tests, deployment runbooks and security checks.
