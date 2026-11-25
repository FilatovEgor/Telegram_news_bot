"""Enforce one publication attempt per article and destination channel."""
from alembic import op

revision = "0004_moderation_publishing"
down_revision = "0003_editorial_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_publication_article_channel",
        "publications",
        ["article_id", "channel_id"],
    )
    op.create_index("ix_publications_status", "publications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_publications_status", table_name="publications")
    op.drop_constraint(
        "uq_publication_article_channel",
        "publications",
        type_="unique",
    )
