"""add outcome metadata to llm cost log"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260501_0021"
down_revision = "20260501_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guards support recovery from partial local migrations; defaults match existing success/no-error rows.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("llm_cost_log")}
    if "outcome" not in columns:
        op.add_column(
            "llm_cost_log",
            sa.Column(
                "outcome",
                sa.String(length=20),
                nullable=False,
                server_default="success",
            ),
        )
    if "error_category" not in columns:
        op.add_column(
            "llm_cost_log",
            sa.Column(
                "error_category",
                sa.String(length=60),
                nullable=False,
                server_default="",
            ),
        )
    if "error_message" not in columns:
        op.add_column(
            "llm_cost_log",
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        )
    indexes = {index["name"] for index in inspector.get_indexes("llm_cost_log")}
    if "ix_llm_cost_log_outcome" not in indexes:
        op.create_index("ix_llm_cost_log_outcome", "llm_cost_log", ["outcome"])
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("llm_cost_log")
    }
    if "ck_llm_cost_log_outcome" not in constraints:
        op.create_check_constraint(
            "ck_llm_cost_log_outcome",
            "llm_cost_log",
            "outcome in ('success', 'error')",
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("llm_cost_log")
    }
    if "ck_llm_cost_log_outcome" in constraints:
        op.drop_constraint("ck_llm_cost_log_outcome", "llm_cost_log", type_="check")
    indexes = {index["name"] for index in inspector.get_indexes("llm_cost_log")}
    if "ix_llm_cost_log_outcome" in indexes:
        op.drop_index("ix_llm_cost_log_outcome", table_name="llm_cost_log")
    columns = {column["name"] for column in inspector.get_columns("llm_cost_log")}
    for column in ("error_message", "error_category", "outcome"):
        if column in columns:
            op.drop_column("llm_cost_log", column)
