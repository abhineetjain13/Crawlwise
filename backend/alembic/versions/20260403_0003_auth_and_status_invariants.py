"""auth and status invariants"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260403_0003"
down_revision = "20260403_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_column(inspector, "users", "token_version"):
        op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    # These updates merge status meanings. A downgrade cannot tell whether an
    # existing "killed"/"failed" row predated this rename or came from it.
    op.execute("UPDATE crawl_runs SET status = 'killed' WHERE status = 'cancelled'")
    op.execute("UPDATE crawl_runs SET status = 'failed' WHERE status = 'degraded'")


def downgrade() -> None:
    raise RuntimeError(
        "Migration 20260403_0003 is not reversible because crawl_run statuses "
        "were merged during upgrade and cannot be mapped back safely."
    )


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
