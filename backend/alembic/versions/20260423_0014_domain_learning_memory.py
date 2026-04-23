"""add domain cookie memory and field feedback tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260423_0014"
down_revision = "20260423_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())

    if "domain_cookie_memory" not in table_names:
        op.create_table(
            "domain_cookie_memory",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column(
                "storage_state",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("state_fingerprint", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "uq_domain_cookie_memory_domain",
            "domain_cookie_memory",
            ["domain"],
            unique=True,
        )

    if "domain_field_feedback" not in table_names:
        op.create_table(
            "domain_field_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("surface", sa.String(length=40), nullable=False),
            sa.Column("field_name", sa.String(length=128), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("source_kind", sa.String(length=32), nullable=False),
            sa.Column("source_value", sa.Text(), nullable=True),
            sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column(
                "payload",
                JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_domain_field_feedback_domain", "domain_field_feedback", ["domain"])
        op.create_index("ix_domain_field_feedback_surface", "domain_field_feedback", ["surface"])
        op.create_index("ix_domain_field_feedback_field_name", "domain_field_feedback", ["field_name"])
        op.create_index("ix_domain_field_feedback_source_run_id", "domain_field_feedback", ["source_run_id"])
        op.create_index(
            "ix_domain_field_feedback_domain_surface",
            "domain_field_feedback",
            ["domain", "surface"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())

    if "domain_field_feedback" in table_names:
        op.drop_index("ix_domain_field_feedback_domain_surface", table_name="domain_field_feedback")
        op.drop_index("ix_domain_field_feedback_source_run_id", table_name="domain_field_feedback")
        op.drop_index("ix_domain_field_feedback_field_name", table_name="domain_field_feedback")
        op.drop_index("ix_domain_field_feedback_surface", table_name="domain_field_feedback")
        op.drop_index("ix_domain_field_feedback_domain", table_name="domain_field_feedback")
        op.drop_table("domain_field_feedback")

    if "domain_cookie_memory" in table_names:
        op.drop_index("uq_domain_cookie_memory_domain", table_name="domain_cookie_memory")
        op.drop_table("domain_cookie_memory")
