"""Prepare the local SQLite database for Alembic startup migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def main() -> int:
    database = Path("data") / "db" / "workbench.db"
    if not database.exists():
        return 0
    with sqlite3.connect(database) as connection:
        has_jobs = bool(
            connection.execute(
                "select count(*) from sqlite_master where type='table' and name='jobs'"
            ).fetchone()[0]
        )
        has_version_table = bool(
            connection.execute(
                "select count(*) from sqlite_master "
                "where type='table' and name='alembic_version'"
            ).fetchone()[0]
        )
        has_version_row = False
        if has_version_table:
            has_version_row = bool(
                connection.execute("select count(*) from alembic_version").fetchone()[0]
            )
    if has_jobs and not has_version_row:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
