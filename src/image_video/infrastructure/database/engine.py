"""SQLite engine creation and initialization."""

import sqlite3
from pathlib import Path
from typing import cast

from sqlalchemy import Engine, create_engine, event

from image_video.infrastructure.database.models import Base


def create_database_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(  # pyright: ignore[reportUnusedFunction]
        dbapi_connection: object, connection_record: object
    ) -> None:
        del connection_record
        connection = cast(sqlite3.Connection, dbapi_connection)
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
