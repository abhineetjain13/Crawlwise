"""auth and status invariants"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260403_0003"
down_revision = "20260403_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    op.execute("UPDATE crawl_runs SET status = 'killed' WHERE status = 'cancelled'")
    op.execute("UPDATE crawl_runs SET status = 'failed' WHERE status = 'degraded'")


def downgrade() -> None:
    op.execute("UPDATE crawl_runs SET status = 'cancelled' WHERE status = 'killed'")
    op.execute("UPDATE crawl_runs SET status = 'degraded' WHERE status = 'failed'")
    op.drop_column("users", "token_version")
