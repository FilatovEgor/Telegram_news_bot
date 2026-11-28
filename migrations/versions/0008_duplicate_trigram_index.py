"""Add trigram index for cross-source duplicate title candidate retrieval."""

from alembic import op

revision = "0008_duplicate_trigram_index"
down_revision = "0007_phase3_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX ix_articles_title_trgm
        ON articles USING gin (lower(title) gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_articles_title_trgm", table_name="articles")
