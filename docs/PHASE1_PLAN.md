# Telegram News Bot 2.0 — Phase 1 implementation plan

## Decisions
- Multiple news sources: MRC plus configurable RSS feeds first; source adapters keep future sites independent.
- AI: OpenAI GPT-4 is the primary provider. A bounded editorial agent may call only local, allowlisted tools. GigaChat remains an optional provider extension.
- Persistence: PostgreSQL from the beginning, SQLAlchemy 2.x async, Alembic migrations.
- Telegram: aiogram 3.x Bot API. Telethon is deferred unless Telegram-channel ingestion from a user account becomes a requirement.
- Runtime/deployment: modern Python, HTTPX, Pydantic Settings, Docker Compose and CI.

## Phase 1 deliverables
1. Separate application startup, Telegram routers, services, sources, AI providers, persistence and scheduling.
2. Move all tokens and connection strings to environment-based settings; keep secrets and database files out of Git.
3. Preserve the uploaded MRC AJAX listing URL, article URL format, selectors, Russian normalization and tag transliteration in a dedicated parser.
4. Add an RSS adapter and source registry for multiple feeds.
5. Use a shared asynchronous HTTP client with TLS verification, timeouts and bounded concurrency.
6. Create PostgreSQL tables for sources, articles, AI outputs, editorial actions, publications and administrators.
7. Add an Alembic initial migration and a one-time SQLite archive importer. The importer must retain original article IDs, links, titles and legacy status/date.
8. Use GPT-4 with bounded tool calling for editorial draft preparation. AI tools must not publish or modify channels; human approval remains mandatory.
9. Add aiogram command handling, admin-only manual ingestion, scheduled ingestion, Docker Compose and CI tests.

## Acceptance criteria
- Lint, unit tests and Python compilation pass in CI.
- App can connect to PostgreSQL and start polling.
- Manual and scheduled ingestion use the same source registry.
- Re-discovered articles are idempotent by source + external ID.
- MRC parser handles malformed or incomplete pages without disabling TLS verification.
- No bot token, AI key, private database, bytecode or local runtime state is committed.
- Legacy status mapping is documented and does not mislabel AI review as channel publication.

## Phases after foundation
- Phase 2: source health, retries, rate limits, canonical URL normalization and cross-source duplicate detection.
- Phase 3: agent workflow for classification, summarization, factual consistency checks and channel-specific drafts, with persisted prompts/tool traces/cost controls.
- Phase 4: approve, reject, edit, regenerate and idempotent publication with Telegram message IDs and audit history.
- Phase 5: multi-channel routing, topic/language profiles, translations and optional Telethon ingestion connector.
- Phase 6: operational metrics, alerts, backups, restore tests, security/dependency checks and production runbooks.

## Database migration note
The project ZIP currently available in the conversation contains a legacy SQLite `motor` table with 646 records. A later database file set has not appeared as an attachment in the current conversation yet. The importer and migrations must be reconciled against those updated database files before treating migration as final. Never commit the SQLite file itself.
