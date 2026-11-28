"""Add an optional pg_trgm index for duplicate-title candidate retrieval."""

from alembic import op

revision = "0008_pg_trgm_title_index"
down_revision = "0007_phase3_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the extension installed on downgrade: it may be shared by other indexes.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_articles_title_trgm "
        "ON articles USING gin (lower(title) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_title_trgm", table_name="articles")
