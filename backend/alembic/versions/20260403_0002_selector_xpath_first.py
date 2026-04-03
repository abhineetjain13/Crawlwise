"""selector xpath-first schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260403_0002"
down_revision = "20260402_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("selectors", sa.Column("css_selector", sa.Text(), nullable=True))
    op.add_column("selectors", sa.Column("xpath", sa.Text(), nullable=True))
    op.add_column("selectors", sa.Column("regex", sa.Text(), nullable=True))
    op.add_column("selectors", sa.Column("status", sa.String(length=20), nullable=True, server_default="pending"))
    op.add_column("selectors", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("selectors", sa.Column("sample_value", sa.Text(), nullable=True))
    op.add_column("selectors", sa.Column("source_run_id", sa.Integer(), nullable=True))
    op.add_column("selectors", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()))
    op.create_index("ix_selectors_source_run_id", "selectors", ["source_run_id"], unique=False)

    op.execute("UPDATE selectors SET css_selector = selector WHERE selector_type = 'css'")
    op.execute("UPDATE selectors SET xpath = selector WHERE selector_type = 'xpath'")
    op.execute("UPDATE selectors SET regex = selector WHERE selector_type = 'regex'")
    op.execute("UPDATE selectors SET status = 'validated' WHERE status IS NULL")
    op.execute("UPDATE selectors SET updated_at = created_at WHERE updated_at IS NULL")

    op.alter_column("selectors", "status", nullable=False, server_default="pending")
    op.alter_column("selectors", "updated_at", nullable=False, server_default=sa.func.now())
    op.create_check_constraint(
        "ck_selectors_has_selector",
        "selectors",
        "css_selector IS NOT NULL OR xpath IS NOT NULL OR regex IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_selectors_status",
        "selectors",
        "status IN ('pending', 'validated', 'manual', 'deterministic', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_selectors_status", "selectors", type_="check")
    op.drop_constraint("ck_selectors_has_selector", "selectors", type_="check")
    op.drop_index("ix_selectors_source_run_id", table_name="selectors")
    op.drop_column("selectors", "updated_at")
    op.drop_column("selectors", "source_run_id")
    op.drop_column("selectors", "sample_value")
    op.drop_column("selectors", "confidence")
    op.drop_column("selectors", "status")
    op.drop_column("selectors", "regex")
    op.drop_column("selectors", "xpath")
    op.drop_column("selectors", "css_selector")
