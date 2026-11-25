"""Add language-aware editorial outputs and publication references."""
import sqlalchemy as sa
from alembic import op

revision = "0005_multilingual_editorial"
down_revision = "0004_moderation_publishing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_outputs",
        sa.Column("language", sa.String(length=16), server_default="und", nullable=False),
    )
    op.create_index("ix_ai_outputs_language", "ai_outputs", ["language"])

    op.add_column(
        "publications",
        sa.Column("ai_output_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "publications",
        sa.Column("language", sa.String(length=16), server_default="ru", nullable=False),
    )
    op.create_foreign_key(
        "fk_publications_ai_output_id_ai_outputs",
        "publications",
        "ai_outputs",
        ["ai_output_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_publications_ai_output_id", "publications", ["ai_output_id"])

    op.execute(
        """
        UPDATE publications AS publication
        SET ai_output_id = (
            SELECT output.id
            FROM ai_outputs AS output
            WHERE output.article_id = publication.article_id
              AND output.output_type = 'editorial_package'
            ORDER BY output.created_at DESC, output.id DESC
            LIMIT 1
        )
        WHERE publication.ai_output_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_publications_ai_output_id", table_name="publications")
    op.drop_constraint(
        "fk_publications_ai_output_id_ai_outputs",
        "publications",
        type_="foreignkey",
    )
    op.drop_column("publications", "language")
    op.drop_column("publications", "ai_output_id")
    op.drop_index("ix_ai_outputs_language", table_name="ai_outputs")
    op.drop_column("ai_outputs", "language")
