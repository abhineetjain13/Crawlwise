"""drop selectors table and selector_memory column"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260406_0007"
down_revision = "20260406_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_promotions") as batch_op:
        batch_op.drop_column("selector_memory")
    op.drop_table("selectors")


def downgrade() -> None:
    op.create_table(
        "selectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False, index=True),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("css_selector", sa.Text(), nullable=True),
        sa.Column("xpath", sa.Text(), nullable=True),
        sa.Column("regex", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sample_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "css_selector IS NOT NULL OR xpath IS NOT NULL OR regex IS NOT NULL",
            name="ck_selectors_has_selector",
        ),
    )
    with op.batch_alter_table("review_promotions") as batch_op:
        batch_op.add_column(sa.Column("selector_memory", sa.JSON(), nullable=False, server_default="{}"))
