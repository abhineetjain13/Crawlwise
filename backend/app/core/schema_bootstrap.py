from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


SELECTOR_COLUMN_PATCHES: tuple[tuple[str, str], ...] = (
    ("css_selector", "ALTER TABLE selectors ADD COLUMN css_selector TEXT"),
    ("xpath", "ALTER TABLE selectors ADD COLUMN xpath TEXT"),
    ("regex", "ALTER TABLE selectors ADD COLUMN regex TEXT"),
    ("status", "ALTER TABLE selectors ADD COLUMN status VARCHAR(20)"),
    ("confidence", "ALTER TABLE selectors ADD COLUMN confidence FLOAT"),
    ("sample_value", "ALTER TABLE selectors ADD COLUMN sample_value TEXT"),
    ("source_run_id", "ALTER TABLE selectors ADD COLUMN source_run_id INTEGER"),
    ("updated_at", "ALTER TABLE selectors ADD COLUMN updated_at DATETIME"),
)


async def ensure_dev_schema(engine: AsyncEngine) -> None:
    """Patch stale local SQLite schemas for development convenience.

    This keeps older local DB files usable after lightweight schema changes.
    It is intentionally narrow and only patches the selector table introduced
    during the XPath-first redesign.
    """
    if not engine.url.drivername.startswith("sqlite"):
        return

    async with engine.begin() as conn:
        tables = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        table_names = {str(row[0]) for row in tables.fetchall()}
        if "selectors" not in table_names:
            return

        pragma_rows = await conn.execute(text("PRAGMA table_info(selectors)"))
        columns = {str(row[1]) for row in pragma_rows.fetchall()}

        for column_name, ddl in SELECTOR_COLUMN_PATCHES:
            if column_name not in columns:
                await conn.execute(text(ddl))

        columns = columns | {name for name, _ in SELECTOR_COLUMN_PATCHES}
        if "selector" in columns and "selector_type" in columns:
            await conn.execute(text("UPDATE selectors SET css_selector = selector WHERE selector_type = 'css' AND css_selector IS NULL"))
            await conn.execute(text("UPDATE selectors SET xpath = selector WHERE selector_type = 'xpath' AND xpath IS NULL"))
            await conn.execute(text("UPDATE selectors SET regex = selector WHERE selector_type = 'regex' AND regex IS NULL"))

        await conn.execute(text("UPDATE selectors SET status = COALESCE(status, 'validated')"))
        await conn.execute(text("UPDATE selectors SET updated_at = COALESCE(updated_at, created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_selectors_source_run_id ON selectors (source_run_id)"))
