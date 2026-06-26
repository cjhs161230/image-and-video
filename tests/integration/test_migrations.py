from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_queue_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    inspector = inspect(create_engine(f"sqlite:///{database_path.as_posix()}"))
    tables = set(inspector.get_table_names())
    assert {
        "jobs",
        "job_events",
        "video_projects",
        "video_reference_images",
        "video_storyboard_versions",
        "video_keyframes",
        "video_frames",
    }.issubset(tables)
    assert "upstream_task_id" in {
        column["name"] for column in inspector.get_columns("video_keyframes")
    }
    assert "client_task_id" in {
        column["name"] for column in inspector.get_columns("video_keyframes")
    }
    assert "result_url" in {
        column["name"] for column in inspector.get_columns("video_keyframes")
    }
    assert "upstream_task_id" in {
        column["name"] for column in inspector.get_columns("video_frames")
    }
    assert "client_task_id" in {
        column["name"] for column in inspector.get_columns("video_frames")
    }
    assert "result_url" in {
        column["name"] for column in inspector.get_columns("video_frames")
    }
