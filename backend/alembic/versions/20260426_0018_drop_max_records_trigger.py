"""drop hard max_records enforcement"""

from __future__ import annotations

from alembic import op

revision = "20260426_0018"
down_revision = "20260425_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    op.execute("DROP TRIGGER IF EXISTS tr_crawl_records_max_records ON crawl_records")
    op.execute("DROP FUNCTION IF EXISTS enforce_crawl_run_max_records()")


def downgrade() -> None:
    return None
