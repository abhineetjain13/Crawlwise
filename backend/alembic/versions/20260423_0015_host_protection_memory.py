"""add host protection memory table"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260423_0015"
down_revision = "20260423_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())

    if "host_protection_memory" in table_names:
        return

    op.create_table(
        "host_protection_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("hard_block_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("browser_first_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proxy_required_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_block_vendor", sa.String(length=64), nullable=True),
        sa.Column("last_block_status_code", sa.Integer(), nullable=True),
        sa.Column("last_block_method", sa.String(length=32), nullable=True),
        sa.Column("last_blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_host_protection_memory_host",
        "host_protection_memory",
        ["host"],
        unique=True,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "host_protection_memory" not in table_names:
        return
    op.drop_index("uq_host_protection_memory_host", table_name="host_protection_memory")
    op.drop_table("host_protection_memory")
