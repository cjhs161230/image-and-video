from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from image_video.application.migration import LegacyMigrator


def create_legacy_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE generations ("
            "id INTEGER PRIMARY KEY, prompt TEXT, save_path TEXT, url_path TEXT)"
        )
        connection.execute(
            "INSERT INTO generations (id, prompt, save_path, url_path) "
            "VALUES (1, 'cat', 'media/cat.png', '')"
        )
        connection.execute(
            "INSERT INTO generations (id, prompt, save_path, url_path) "
            "VALUES (2, 'dog', '', 'missing.png')"
        )
        connection.commit()


def test_legacy_migration_uses_backup_copies_media_and_reports_missing(
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    legacy_db = legacy_root / "legacy.db"
    media = legacy_root / "media" / "cat.png"
    media.parent.mkdir()
    media.write_bytes(b"cat")
    create_legacy_db(legacy_db)
    (legacy_root / "old.log").write_text("log", encoding="utf-8")
    (legacy_root / "config.json").write_text('{"api_key":"secret"}', encoding="utf-8")
    target_root = tmp_path / "data" / "migration"

    report = LegacyMigrator(legacy_root=legacy_root, target_root=target_root).run(
        legacy_db
    )

    assert (target_root / "snapshots" / "legacy.db").is_file()
    assert report["records_total"] == 2
    assert report["copied"] == 1
    assert report["missing"] == 1
    assert report["items"][0]["sha256"]
    assert report["items"][1]["status"] == "missing"
    assert (target_root / "logs" / "old.log").read_text(encoding="utf-8") == "log"
    assert not (target_root / "config.json").exists()
    saved_report = json.loads((target_root / "migration_report.json").read_text())
    assert saved_report["records_total"] == 2
