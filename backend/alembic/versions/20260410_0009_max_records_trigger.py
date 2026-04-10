"""enforce max_records at the database level via triggers"""

from __future__ import annotations

from alembic import op

revision = "20260410_0009"
down_revision = "20260408_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_crawl_run_max_records()
        RETURNS trigger AS $$
        DECLARE
            configured_max integer;
            current_count integer;
        BEGIN
            SELECT NULLIF(crawl_runs.settings->>'max_records', '')::integer
            INTO configured_max
            FROM crawl_runs
            WHERE crawl_runs.id = NEW.run_id;

            IF configured_max IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT COUNT(*)
            INTO current_count
            FROM crawl_records
            WHERE crawl_records.run_id = NEW.run_id;

            IF current_count > configured_max THEN
                RAISE EXCEPTION 'max_records exceeded for run %', NEW.run_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trigger_enforce_crawl_run_max_records
        AFTER INSERT OR UPDATE OF run_id ON crawl_records
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION enforce_crawl_run_max_records();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_crawl_run_max_records_on_settings()
        RETURNS trigger AS $$
        DECLARE
            configured_max integer;
            current_count integer;
        BEGIN
            configured_max := NULLIF(NEW.settings->>'max_records', '')::integer;
            IF configured_max IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT COUNT(*)
            INTO current_count
            FROM crawl_records
            WHERE crawl_records.run_id = NEW.id;

            IF current_count > configured_max THEN
                RAISE EXCEPTION 'max_records below existing record count for run %', NEW.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trigger_enforce_crawl_run_max_records_on_settings
        BEFORE INSERT OR UPDATE OF settings ON crawl_runs
        FOR EACH ROW
        EXECUTE FUNCTION enforce_crawl_run_max_records_on_settings();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_enforce_crawl_run_max_records_on_settings ON crawl_runs")
    op.execute("DROP FUNCTION IF EXISTS enforce_crawl_run_max_records_on_settings()")
    op.execute("DROP TRIGGER IF EXISTS trigger_enforce_crawl_run_max_records ON crawl_records")
    op.execute("DROP FUNCTION IF EXISTS enforce_crawl_run_max_records()")
