"""selector xpath-first schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260403_0002"
down_revision = "20260402_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "selectors", "css_selector"):
        op.add_column("selectors", sa.Column("css_selector", sa.Text(), nullable=True))
    if not _has_column(inspector, "selectors", "xpath"):
        op.add_column("selectors", sa.Column("xpath", sa.Text(), nullable=True))
    if not _has_column(inspector, "selectors", "regex"):
        op.add_column("selectors", sa.Column("regex", sa.Text(), nullable=True))
    if not _has_column(inspector, "selectors", "status"):
        op.add_column("selectors", sa.Column("status", sa.String(length=20), nullable=True, server_default="pending"))
    if not _has_column(inspector, "selectors", "confidence"):
        op.add_column("selectors", sa.Column("confidence", sa.Float(), nullable=True))
    if not _has_column(inspector, "selectors", "sample_value"):
        op.add_column("selectors", sa.Column("sample_value", sa.Text(), nullable=True))
    if not _has_column(inspector, "selectors", "source_run_id"):
        op.add_column("selectors", sa.Column("source_run_id", sa.Integer(), nullable=True))
    if not _has_column(inspector, "selectors", "updated_at"):
        op.add_column("selectors", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()))
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "selectors", "ix_selectors_source_run_id"):
        op.create_index("ix_selectors_source_run_id", "selectors", ["source_run_id"], unique=False)

    op.execute("UPDATE selectors SET css_selector = selector WHERE selector_type = 'css'")
    op.execute("UPDATE selectors SET xpath = selector WHERE selector_type = 'xpath'")
    op.execute("UPDATE selectors SET regex = selector WHERE selector_type = 'regex'")
    op.execute("UPDATE selectors SET status = 'validated' WHERE status IS NULL")
    op.execute("UPDATE selectors SET updated_at = created_at WHERE updated_at IS NULL")

    with op.batch_alter_table("selectors") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default="pending",
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        if not _has_constraint(inspector, "selectors", "ck_selectors_has_selector"):
            batch_op.create_check_constraint(
                "ck_selectors_has_selector",
                "css_selector IS NOT NULL OR xpath IS NOT NULL OR regex IS NOT NULL",
            )
        if not _has_constraint(inspector, "selectors", "ck_selectors_status"):
            batch_op.create_check_constraint(
                "ck_selectors_status",
                "status IN ('pending', 'validated', 'manual', 'deterministic', 'rejected')",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, "selectors", "ix_selectors_source_run_id"):
        op.drop_index("ix_selectors_source_run_id", table_name="selectors")
    with op.batch_alter_table("selectors") as batch_op:
        if _has_constraint(inspector, "selectors", "ck_selectors_status"):
            batch_op.drop_constraint("ck_selectors_status", type_="check")
        if _has_constraint(inspector, "selectors", "ck_selectors_has_selector"):
            batch_op.drop_constraint("ck_selectors_has_selector", type_="check")
    inspector = sa.inspect(bind)
    for column_name in ("updated_at", "source_run_id", "sample_value", "confidence", "status", "regex", "xpath", "css_selector"):
        if _has_column(inspector, "selectors", column_name):
            op.drop_column("selectors", column_name)
            inspector = sa.inspect(bind)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def _has_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }
