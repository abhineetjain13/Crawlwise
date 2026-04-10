"""drop site memory table"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260406_0006"
down_revision = "20260405_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("site_memory")


def downgrade() -> None:
    op.create_table(
        "site_memory",
        sa.Column("domain", sa.String(length=255), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("last_crawl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
