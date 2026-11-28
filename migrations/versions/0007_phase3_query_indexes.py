"""Add indexes for editorial queues and latest AI output lookups."""

from alembic import op

revision = "0007_phase3_query_indexes"
down_revision = "0006_article_duplicate_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_articles_status_created_at_id",
        "articles",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "ix_ai_outputs_article_type_created_id",
        "ai_outputs",
        ["article_id", "output_type", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_outputs_article_type_created_id", table_name="ai_outputs")
    op.drop_index("ix_articles_status_created_at_id", table_name="articles")
