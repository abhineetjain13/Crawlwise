"""initial schema"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260402_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_type", sa.String(length=20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("requested_fields", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "crawl_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("discovered_data", sa.JSON(), nullable=False),
        sa.Column("source_trace", sa.JSON(), nullable=False),
        sa.Column("raw_html_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "crawl_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id"), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "selectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("field_name", sa.String(length=255), nullable=False),
        sa.Column("selector", sa.Text(), nullable=False),
        sa.Column("selector_type", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "llm_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("task_type", sa.String(length=60), nullable=False),
        sa.Column("per_domain_daily_budget_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("global_session_budget_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "llm_cost_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id"), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("task_type", sa.String(length=60), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "review_promotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id"), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("approved_schema", sa.JSON(), nullable=False),
        sa.Column("field_mapping", sa.JSON(), nullable=False),
        sa.Column("selector_memory", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("review_promotions")
    op.drop_table("llm_cost_log")
    op.drop_table("llm_configs")
    op.drop_table("selectors")
    op.drop_table("crawl_logs")
    op.drop_table("crawl_records")
    op.drop_table("crawl_runs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
