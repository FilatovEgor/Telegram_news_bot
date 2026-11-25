"""Source health, ingestion runs and duplicate candidates."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_phase2_source_health"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_sources", sa.Column("last_status", sa.String(length=16), nullable=True))
    op.add_column("news_sources", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("news_sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("news_sources", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "news_sources",
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("news_sources", sa.Column("last_duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "news_sources",
        sa.Column("last_fetched_count", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "source_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("attempted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_source_runs_source_id", "source_runs", ["source_id"])
    op.create_index("ix_source_runs_started_at", "source_runs", ["started_at"])

    op.create_table(
        "article_duplicates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article_id_left", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id_right", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["article_id_left"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id_right"], ["articles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("article_id_left", "article_id_right", name="uq_article_duplicate_pair"),
    )
    op.create_index("ix_article_duplicates_article_id_left", "article_duplicates", ["article_id_left"])
    op.create_index("ix_article_duplicates_article_id_right", "article_duplicates", ["article_id_right"])
    op.create_index("ix_article_duplicates_review_status", "article_duplicates", ["review_status"])


def downgrade() -> None:
    op.drop_index("ix_article_duplicates_review_status", table_name="article_duplicates")
    op.drop_index("ix_article_duplicates_article_id_right", table_name="article_duplicates")
    op.drop_index("ix_article_duplicates_article_id_left", table_name="article_duplicates")
    op.drop_table("article_duplicates")
    op.drop_index("ix_source_runs_started_at", table_name="source_runs")
    op.drop_index("ix_source_runs_source_id", table_name="source_runs")
    op.drop_table("source_runs")
    op.drop_column("news_sources", "last_fetched_count")
    op.drop_column("news_sources", "last_duration_ms")
    op.drop_column("news_sources", "consecutive_failures")
    op.drop_column("news_sources", "last_error")
    op.drop_column("news_sources", "last_success_at")
    op.drop_column("news_sources", "last_attempt_at")
    op.drop_column("news_sources", "last_status")
