"""remove selector confidence column"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260403_0004"
down_revision = "20260403_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("selectors") as batch_op:
        batch_op.drop_column("confidence")


def downgrade() -> None:
    with op.batch_alter_table("selectors") as batch_op:
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
