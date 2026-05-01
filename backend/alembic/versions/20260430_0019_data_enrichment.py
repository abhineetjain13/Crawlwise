"""add data enrichment foundation"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260430_0019"
down_revision = "20260426_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    crawl_record_columns = {
        column["name"] for column in inspector.get_columns("crawl_records")
    }

    if "enrichment_status" not in crawl_record_columns:
        op.add_column(
            "crawl_records",
            sa.Column(
                "enrichment_status",
                sa.String(length=32),
                nullable=False,
                server_default="unenriched",
            ),
        )
        op.create_index(
            "ix_crawl_records_enrichment_status",
            "crawl_records",
            ["enrichment_status"],
        )
    if "enriched_at" not in crawl_record_columns:
        op.add_column(
            "crawl_records",
            sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "data_enrichment_jobs" not in table_names:
        op.create_table(
            "data_enrichment_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "source_run_id",
                sa.Integer(),
                sa.ForeignKey("crawl_runs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("options", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_data_enrichment_jobs_user_id", "data_enrichment_jobs", ["user_id"])
        op.create_index("ix_data_enrichment_jobs_source_run_id", "data_enrichment_jobs", ["source_run_id"])
        op.create_index("ix_data_enrichment_jobs_status", "data_enrichment_jobs", ["status"])

    if "enriched_products" not in table_names:
        op.create_table(
            "enriched_products",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "job_id",
                sa.Integer(),
                sa.ForeignKey("data_enrichment_jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_run_id",
                sa.Integer(),
                sa.ForeignKey("crawl_runs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "source_record_id",
                sa.Integer(),
                sa.ForeignKey("crawl_records.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("price_normalized", JSONB, nullable=True),
            sa.Column("color_family", sa.Text(), nullable=True),
            sa.Column("size_normalized", JSONB, nullable=True),
            sa.Column("size_system", sa.String(length=32), nullable=True),
            sa.Column("gender_normalized", sa.String(length=32), nullable=True),
            sa.Column("materials_normalized", JSONB, nullable=True),
            sa.Column("availability_normalized", sa.String(length=32), nullable=True),
            sa.Column("seo_keywords", JSONB, nullable=True),
            sa.Column("category_path", sa.Text(), nullable=True),
            sa.Column("intent_attributes", JSONB, nullable=True),
            sa.Column("audience", JSONB, nullable=True),
            sa.Column("style_tags", JSONB, nullable=True),
            sa.Column("ai_discovery_tags", JSONB, nullable=True),
            sa.Column("suggested_bundles", JSONB, nullable=True),
            sa.Column("diagnostics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_enriched_products_job_id", "enriched_products", ["job_id"])
        op.create_index("ix_enriched_products_source_run_id", "enriched_products", ["source_run_id"])
        op.create_index("ix_enriched_products_source_record_id", "enriched_products", ["source_record_id"])
        op.create_index("ix_enriched_products_status", "enriched_products", ["status"])
        op.create_index(
            "uq_enriched_products_source_record",
            "enriched_products",
            ["source_record_id"],
            unique=True,
            postgresql_where=sa.text("source_record_id IS NOT NULL"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "enriched_products" in table_names:
        op.drop_table("enriched_products")
    if "data_enrichment_jobs" in table_names:
        op.drop_table("data_enrichment_jobs")
    crawl_record_columns = {
        column["name"] for column in inspector.get_columns("crawl_records")
    }
    if "enriched_at" in crawl_record_columns:
        op.drop_column("crawl_records", "enriched_at")
    if "enrichment_status" in crawl_record_columns:
        try:
            op.drop_index("ix_crawl_records_enrichment_status", table_name="crawl_records")
        except Exception:
            pass
        op.drop_column("crawl_records", "enrichment_status")
