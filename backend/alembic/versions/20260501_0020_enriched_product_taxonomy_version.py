"""add taxonomy version to enriched products"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260501_0020"
down_revision = "20260430_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("enriched_products")}
    if "taxonomy_version" not in columns:
        op.add_column(
            "enriched_products",
            sa.Column("taxonomy_version", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("enriched_products")}
    if "taxonomy_version" in columns:
        op.drop_column("enriched_products", "taxonomy_version")
