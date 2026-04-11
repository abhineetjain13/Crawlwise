"""add url_identity_key column and unique partial index for listing deduplication"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260411_0011"
down_revision = "20260410_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawl_records",
        sa.Column("url_identity_key", sa.String(64), nullable=True),
    )
    # Unique partial index: prevents duplicate records within the same run
    # when a batch pauses, fails, and resumes or when pagination overlaps.
    # Only applies to rows that have a computed identity key.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_crawl_records_run_identity
        ON crawl_records (run_id, url_identity_key)
        WHERE url_identity_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_crawl_records_run_identity")
    op.drop_column("crawl_records", "url_identity_key")
