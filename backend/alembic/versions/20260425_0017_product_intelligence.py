"""add product intelligence tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260425_0017"
down_revision = "20260424_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())

    if "product_intelligence_jobs" not in table_names:
        op.create_table(
            "product_intelligence_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("options", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_product_intelligence_jobs_user_id", "product_intelligence_jobs", ["user_id"])
        op.create_index("ix_product_intelligence_jobs_source_run_id", "product_intelligence_jobs", ["source_run_id"])
        op.create_index("ix_product_intelligence_jobs_status", "product_intelligence_jobs", ["status"])

    if "product_intelligence_source_products" not in table_names:
        op.create_table(
            "product_intelligence_source_products",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("product_intelligence_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("crawl_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("brand", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("normalized_brand", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("title", sa.Text(), nullable=False, server_default=""),
            sa.Column("sku", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("mpn", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("gtin", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("currency", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("image_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_private_label", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_product_intelligence_source_products_job_id", "product_intelligence_source_products", ["job_id"])
        op.create_index("ix_product_intelligence_source_products_source_run_id", "product_intelligence_source_products", ["source_run_id"])
        op.create_index("ix_product_intelligence_source_products_source_record_id", "product_intelligence_source_products", ["source_record_id"])
        op.create_index("ix_product_intelligence_source_products_brand", "product_intelligence_source_products", ["brand"])
        op.create_index("ix_product_intelligence_source_products_normalized_brand", "product_intelligence_source_products", ["normalized_brand"])

    if "product_intelligence_candidates" not in table_names:
        op.create_table(
            "product_intelligence_candidates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("product_intelligence_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_product_id", sa.Integer(), sa.ForeignKey("product_intelligence_source_products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("candidate_crawl_run_id", sa.Integer(), sa.ForeignKey("crawl_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("source_type", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("query_used", sa.Text(), nullable=False, server_default=""),
            sa.Column("search_rank", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="discovered"),
            sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_product_intelligence_candidates_job_id", "product_intelligence_candidates", ["job_id"])
        op.create_index("ix_product_intelligence_candidates_source_product_id", "product_intelligence_candidates", ["source_product_id"])
        op.create_index("ix_product_intelligence_candidates_candidate_crawl_run_id", "product_intelligence_candidates", ["candidate_crawl_run_id"])
        op.create_index("ix_product_intelligence_candidates_domain", "product_intelligence_candidates", ["domain"])
        op.create_index("ix_product_intelligence_candidates_status", "product_intelligence_candidates", ["status"])

    if "product_intelligence_matches" not in table_names:
        op.create_table(
            "product_intelligence_matches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("product_intelligence_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_product_id", sa.Integer(), sa.ForeignKey("product_intelligence_source_products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("product_intelligence_candidates.id", ondelete="CASCADE"), nullable=False),
            sa.Column("candidate_record_id", sa.Integer(), sa.ForeignKey("crawl_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("score_label", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("source_price", sa.Float(), nullable=True),
            sa.Column("candidate_price", sa.Float(), nullable=True),
            sa.Column("currency", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("availability", sa.Text(), nullable=False, server_default=""),
            sa.Column("candidate_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("candidate_domain", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("score_reasons", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("llm_enrichment", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_product_intelligence_matches_job_id", "product_intelligence_matches", ["job_id"])
        op.create_index("ix_product_intelligence_matches_source_product_id", "product_intelligence_matches", ["source_product_id"])
        op.create_index("ix_product_intelligence_matches_candidate_id", "product_intelligence_matches", ["candidate_id"])
        op.create_index("ix_product_intelligence_matches_candidate_record_id", "product_intelligence_matches", ["candidate_record_id"])
        op.create_index("ix_product_intelligence_matches_score", "product_intelligence_matches", ["score"])
        op.create_index("ix_product_intelligence_matches_review_status", "product_intelligence_matches", ["review_status"])
        op.create_index("ix_product_intelligence_matches_candidate_domain", "product_intelligence_matches", ["candidate_domain"])
        op.create_index("ix_product_intelligence_matches_job_source", "product_intelligence_matches", ["job_id", "source_product_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "product_intelligence_matches" in table_names:
        op.drop_table("product_intelligence_matches")
    if "product_intelligence_candidates" in table_names:
        op.drop_table("product_intelligence_candidates")
    if "product_intelligence_source_products" in table_names:
        op.drop_table("product_intelligence_source_products")
    if "product_intelligence_jobs" in table_names:
        op.drop_table("product_intelligence_jobs")
