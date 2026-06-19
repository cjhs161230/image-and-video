from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_queue_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(f"sqlite:///{database_path.as_posix()}")).get_table_names())
    assert {
        "jobs",
        "job_events",
        "video_projects",
        "video_reference_images",
        "video_storyboard_versions",
    }.issubset(tables)
