"""persist host protection success method"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260424_0016"
down_revision = "20260423_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "host_protection_memory" not in table_names:
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("host_protection_memory")
    }
    if "last_success_method" not in columns:
        op.add_column(
            "host_protection_memory",
            sa.Column("last_success_method", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "host_protection_memory" not in table_names:
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("host_protection_memory")
    }
    if "last_success_method" in columns:
        op.drop_column("host_protection_memory", "last_success_method")
