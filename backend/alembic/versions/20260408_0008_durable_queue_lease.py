"""add durable queue lease fields to crawl_runs"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260408_0008"
down_revision = "20260406_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_runs") as batch_op:
        batch_op.add_column(sa.Column("queue_owner", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("last_claimed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.alter_column(
            "claim_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=None,
        )
        batch_op.create_index("ix_crawl_runs_queue_owner", ["queue_owner"], unique=False)
        batch_op.create_index(
            "ix_crawl_runs_lease_expires_at", ["lease_expires_at"], unique=False
        )
def downgrade() -> None:
    with op.batch_alter_table("crawl_runs") as batch_op:
        batch_op.drop_index("ix_crawl_runs_lease_expires_at")
        batch_op.drop_index("ix_crawl_runs_queue_owner")
        batch_op.drop_column("last_claimed_at")
        batch_op.drop_column("claim_count")
        batch_op.drop_column("last_heartbeat_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("queue_owner")
