"""add crawl record content fingerprint"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260508_0022"
down_revision = "20260501_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("crawl_records")}
    if "content_fingerprint" not in columns:
        op.add_column(
            "crawl_records",
            sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        )
    indexes = {index["name"] for index in inspector.get_indexes("crawl_records")}
    if "ix_crawl_records_run_content_fp" not in indexes:
        op.create_index(
            "ix_crawl_records_run_content_fp",
            "crawl_records",
            ["run_id", "content_fingerprint"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("crawl_records")}
    if "ix_crawl_records_run_content_fp" in indexes:
        op.drop_index("ix_crawl_records_run_content_fp", table_name="crawl_records")
    columns = {column["name"] for column in inspector.get_columns("crawl_records")}
    if "content_fingerprint" in columns:
        op.drop_column("crawl_records", "content_fingerprint")
