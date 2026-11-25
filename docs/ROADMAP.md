# Telegram News Bot 2.0 Roadmap

## Decisions
- Sources: MRC plus configurable RSS feeds, with adapter interfaces for future sources.
- AI: OpenAI GPT-4 primary; bounded editorial agent with allowlisted tools; GigaChat optional extension.
- Database: PostgreSQL from the beginning, SQLAlchemy 2.x async, Alembic.
- Telegram: aiogram 3.x Bot API; Telethon only if user-account Telegram channel ingestion becomes necessary.
- Runtime: Python 3.13, HTTPX, Pydantic Settings, Docker Compose.

## Phase 1 — foundation
- Separate bot, services, sources, AI and persistence packages.
- Add typed environment settings and secret-safe configuration.
- Preserve MRC listing endpoint, URL scheme, parser selectors, text normalization and tag transliteration.
- Add configurable RSS feeds and a shared async HTTP client with TLS verification.
- Add PostgreSQL tables for sources, articles, AI outputs, editorial actions, publications and admins.
- Add Alembic initial migration and legacy SQLite importer.
- Add GPT-4 tool-calling foundation. Its allowlisted tools validate drafts and format previews; none can publish.
- Add admin-only /load, scheduled ingestion, Docker and CI.
- Keep uploaded SQLite data out of Git. Migrate from a protected local backup.

## Phase 2 — ingestion quality (implemented)
- Add bounded retry and exponential backoff for transport failures, HTTP 429 and HTTP 5xx responses; honor bounded Retry-After values.
- Add shared request spacing and configurable MRC article concurrency.
- Track per-source health and append-only run history, including duration, attempted/fetched/failed counts and warnings.
- Add admin-only /sources health reporting.
- Canonicalize stored article URLs and normalize content hashes.
- Detect cross-source duplicate candidates by canonical URL, content hash or title similarity. Candidates remain pending human review; source articles are preserved and never auto-merged or discarded.
- Add PostgreSQL migration and CI migration verification plus parser/retry/canonicalization tests.

## Phase 3 — editorial agent
- Article classification, summaries, number/entity checks and channel variants.
- Persist provider/model, prompt version, tool traces and validation results.
- Add budget/time limits and bounded retries.
- Human approval remains mandatory; agent is not allowed to publish directly.
- Add GigaChat as a selectable provider implementation if required.

## Phase 4 — moderation and publishing
- Preview, regenerate, edit, approve and reject actions.
- Role-based admin permissions and audit history.
- Approved-only publishing, Telegram message IDs and idempotent retries.

## Phase 5 — multi-channel operations
- Multi-channel and topic/language routing, translation and publishing windows.
- Optional Telethon ingestion connector, isolated from the aiogram bot.

## Phase 6 — production
- Metrics, alerts, backups, restore tests, security checks and deployment runbooks.
