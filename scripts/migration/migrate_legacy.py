"""Run legacy data migration into data/migration.

Usage:
    python scripts/migration/migrate_legacy.py <legacy_root> <legacy_database>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from image_video.application.migration import LegacyMigrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_root", type=Path)
    parser.add_argument("legacy_database", type=Path)
    parser.add_argument("--target-root", type=Path, default=Path("data") / "migration")
    args = parser.parse_args()
    report = LegacyMigrator(
        legacy_root=args.legacy_root,
        target_root=args.target_root,
    ).run(args.legacy_database)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
