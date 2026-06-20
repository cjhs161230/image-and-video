"""Local worker entry point."""

from __future__ import annotations

import time


def main() -> int:
    while True:
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
