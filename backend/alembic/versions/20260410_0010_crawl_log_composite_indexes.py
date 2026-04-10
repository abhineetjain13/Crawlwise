"""add composite indexes on crawl_logs(run_id, created_at)/(run_id, level) and crawl_runs(user_id, created_at)"""

from __future__ import annotations

from alembic import op

revision = "20260410_0010"
down_revision = "20260410_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_crawl_logs_run_id_created_at",
        "crawl_logs",
        ["run_id", "created_at"],
    )
    op.create_index(
        "ix_crawl_logs_run_id_level",
        "crawl_logs",
        ["run_id", "level"],
    )
    op.create_index(
        "ix_crawl_runs_user_id_created_at",
        "crawl_runs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_runs_user_id_created_at", table_name="crawl_runs")
    op.drop_index("ix_crawl_logs_run_id_level", table_name="crawl_logs")
    op.drop_index("ix_crawl_logs_run_id_created_at", table_name="crawl_logs")
