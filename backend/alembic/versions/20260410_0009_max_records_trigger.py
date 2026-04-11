"""enforce crawl run max_records at the database layer"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260410_0009"
down_revision = "20260408_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION enforce_crawl_run_max_records()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                configured_limit integer;
            BEGIN
                SELECT GREATEST(
                    COALESCE(
                        CASE
                            WHEN COALESCE(crawl_runs.settings->>'max_records', '') ~ '^[0-9]+$'
                                THEN (crawl_runs.settings->>'max_records')::integer
                        END,
                        100
                    ),
                    1
                )
                INTO configured_limit
                FROM crawl_runs
                WHERE crawl_runs.id = NEW.run_id
                FOR UPDATE;

                IF configured_limit IS NULL THEN
                    configured_limit := 100;
                END IF;

                IF (
                    SELECT COUNT(*)
                    FROM crawl_records
                    WHERE crawl_records.run_id = NEW.run_id
                ) >= configured_limit THEN
                    RAISE EXCEPTION
                        'crawl_records max_records exceeded for run %',
                        NEW.run_id
                        USING ERRCODE = '23514';
                END IF;

                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DROP TRIGGER IF EXISTS tr_crawl_records_max_records ON crawl_records;
            CREATE TRIGGER tr_crawl_records_max_records
            BEFORE INSERT ON crawl_records
            FOR EACH ROW
            EXECUTE FUNCTION enforce_crawl_run_max_records();
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    op.execute("DROP TRIGGER IF EXISTS tr_crawl_records_max_records ON crawl_records")
    op.execute("DROP FUNCTION IF EXISTS enforce_crawl_run_max_records()")
