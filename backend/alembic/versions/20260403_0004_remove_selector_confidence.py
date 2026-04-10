"""remove selector confidence column"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260403_0004"
down_revision = "20260403_0003"
branch_labels = None
depends_on = None

_BACKUP_TABLE = "selector_confidence_backup"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "selectors", "confidence"):
        if not inspector.has_table(_BACKUP_TABLE):
            op.create_table(
                _BACKUP_TABLE,
                sa.Column("selector_id", sa.Integer(), primary_key=True, nullable=False),
                sa.Column("confidence", sa.Float(), nullable=True),
            )
        else:
            op.execute(sa.text(f"DELETE FROM {_BACKUP_TABLE}"))
        op.execute(
            sa.text(
                f"""
                INSERT INTO {_BACKUP_TABLE} (selector_id, confidence)
                SELECT id, confidence
                FROM selectors
                WHERE confidence IS NOT NULL
                """
            )
        )
        with op.batch_alter_table("selectors") as batch_op:
            batch_op.drop_column("confidence")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "selectors", "confidence"):
        with op.batch_alter_table("selectors") as batch_op:
            batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
    inspector = sa.inspect(bind)
    if inspector.has_table(_BACKUP_TABLE) and _has_column(inspector, "selectors", "confidence"):
        op.execute(
            sa.text(
                f"""
                UPDATE selectors
                SET confidence = (
                    SELECT backup.confidence
                    FROM {_BACKUP_TABLE} AS backup
                    WHERE backup.selector_id = selectors.id
                )
                WHERE EXISTS (
                    SELECT 1
                    FROM {_BACKUP_TABLE} AS backup
                    WHERE backup.selector_id = selectors.id
                )
                """
            )
        )


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
