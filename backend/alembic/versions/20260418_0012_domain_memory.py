"""add domain memory table"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260418_0012"
down_revision = "20260411_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "domain_memory" in inspector.get_table_names():
        return
    op.create_table(
        "domain_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=True),
        sa.Column("selectors", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_domain_memory_domain", "domain_memory", ["domain"])
    op.create_index("ix_domain_memory_surface", "domain_memory", ["surface"])


def downgrade() -> None:
    op.drop_index("ix_domain_memory_surface", table_name="domain_memory")
    op.drop_index("ix_domain_memory_domain", table_name="domain_memory")
    op.drop_table("domain_memory")
