"""Persist structured editorial packages, validation and execution traces."""
import sqlalchemy as sa
from alembic import op

revision = "0003_editorial_pipeline"
down_revision = "0002_phase2_source_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_outputs",
        sa.Column("status", sa.String(length=24), server_default="LEGACY", nullable=False),
    )
    op.add_column("ai_outputs", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    op.add_column(
        "ai_outputs",
        sa.Column("validation_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "ai_outputs",
        sa.Column("tool_trace", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "ai_outputs",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "ai_outputs",
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("ai_outputs", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_outputs", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.create_index("ix_ai_outputs_status", "ai_outputs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_outputs_status", table_name="ai_outputs")
    op.drop_column("ai_outputs", "output_tokens")
    op.drop_column("ai_outputs", "input_tokens")
    op.drop_column("ai_outputs", "duration_ms")
    op.drop_column("ai_outputs", "attempt_count")
    op.drop_column("ai_outputs", "tool_trace")
    op.drop_column("ai_outputs", "validation_json")
    op.drop_column("ai_outputs", "prompt_version")
    op.drop_column("ai_outputs", "status")
