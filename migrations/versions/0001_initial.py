"""Initial PostgreSQL schema."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_news_sources_source_key"),
    )
    op.create_table(
        "articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(1024), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
        sa.Column("legacy_row_id", sa.Integer()),
        sa.Column("legacy_status", sa.String(128)),
        sa.Column("legacy_date", sa.String(128)),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_article_source_external_id"),
    )
    op.create_index("ix_articles_source_id", "articles", ["source_id"])
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"])
    op.create_index("ix_articles_status", "articles", ["status"])
    op.create_table(
        "ai_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("output_type", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_outputs_article_id", "ai_outputs", ["article_id"])
    op.create_table(
        "editorial_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_telegram_id", sa.Integer()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_editorial_actions_article_id", "editorial_actions", ["article_id"])
    op.create_table(
        "publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("message_id", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("channel_id", "message_id", name="uq_publication_channel_message"),
    )
    op.create_index("ix_publications_article_id", "publications", ["article_id"])
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_user_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("telegram_user_id", name="uq_admin_users_telegram_user_id"),
    )


def downgrade() -> None:
    op.drop_table("admin_users")
    op.drop_index("ix_publications_article_id", table_name="publications")
    op.drop_table("publications")
    op.drop_index("ix_editorial_actions_article_id", table_name="editorial_actions")
    op.drop_table("editorial_actions")
    op.drop_index("ix_ai_outputs_article_id", table_name="ai_outputs")
    op.drop_table("ai_outputs")
    op.drop_index("ix_articles_status", table_name="articles")
    op.drop_index("ix_articles_content_hash", table_name="articles")
    op.drop_index("ix_articles_source_id", table_name="articles")
    op.drop_table("articles")
    op.drop_table("news_sources")
