"""add domain run profiles table"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260423_0013"
down_revision = "20260418_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "domain_run_profiles" in inspector.get_table_names():
        return
    op.create_table(
        "domain_run_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("profile", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_domain_run_profiles_domain", "domain_run_profiles", ["domain"])
    op.create_index("ix_domain_run_profiles_surface", "domain_run_profiles", ["surface"])
    op.create_index(
        "uq_domain_run_profiles_domain_surface",
        "domain_run_profiles",
        ["domain", "surface"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_domain_run_profiles_domain_surface", table_name="domain_run_profiles")
    op.drop_index("ix_domain_run_profiles_surface", table_name="domain_run_profiles")
    op.drop_index("ix_domain_run_profiles_domain", table_name="domain_run_profiles")
    op.drop_table("domain_run_profiles")
