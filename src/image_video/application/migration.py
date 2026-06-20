"""Legacy project migration helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any


class LegacyMigrator:
    def __init__(self, *, legacy_root: Path, target_root: Path):
        self.legacy_root = legacy_root
        self.target_root = target_root

    def run(self, database_path: Path) -> dict[str, Any]:
        self.target_root.mkdir(parents=True, exist_ok=True)
        snapshot = self._backup_database(database_path)
        items = self._migrate_records(snapshot)
        self._archive_logs()
        report = {
            "records_total": len(items),
            "copied": sum(1 for item in items if item["status"] == "copied"),
            "missing": sum(1 for item in items if item["status"] == "missing"),
            "items": items,
        }
        (self.target_root / "migration_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report

    def _backup_database(self, database_path: Path) -> Path:
        snapshot_dir = self.target_root / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot = snapshot_dir / database_path.name
        with (
            sqlite3.connect(
                f"file:{database_path.as_posix()}?mode=ro",
                uri=True,
            ) as source,
            sqlite3.connect(snapshot) as target,
        ):
            source.backup(target)
        return snapshot

    def _migrate_records(self, snapshot: Path) -> list[dict[str, Any]]:
        media_dir = self.target_root / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        with sqlite3.connect(snapshot) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, prompt, save_path, url_path FROM generations ORDER BY id"
            ).fetchall()
        for row in rows:
            source = self._locate_media(row["save_path"], row["url_path"])
            item: dict[str, Any] = {
                "legacy_id": row["id"],
                "prompt": row["prompt"],
                "status": "missing",
            }
            if source is not None:
                destination = media_dir / f"{row['id']}_{source.name}"
                shutil.copy2(source, destination)
                item.update(
                    {
                        "status": "copied",
                        "path": destination.as_posix(),
                        "size": destination.stat().st_size,
                        "sha256": self._sha256(destination),
                    }
                )
            items.append(item)
        return items

    def _locate_media(self, save_path: str, url_path: str) -> Path | None:
        for value in [save_path, url_path]:
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = self.legacy_root / candidate
            if candidate.is_file():
                return candidate
        return None

    def _archive_logs(self) -> None:
        log_dir = self.target_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        for log_file in self.legacy_root.glob("*.log"):
            shutil.copy2(log_file, log_dir / log_file.name)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
