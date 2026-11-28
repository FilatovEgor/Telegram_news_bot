"""Index article creation time and source for bounded duplicate scans."""

import sqlalchemy as sa
from alembic import op

revision = "0006_article_duplicate_lookup"
down_revision = "0005_multilingual_editorial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_articles_created_at_source_id",
        "articles",
        ["created_at", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_articles_created_at_source_id", table_name="articles")
