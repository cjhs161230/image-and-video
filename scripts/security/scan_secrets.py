"""Scan source trees for credentials that must not enter version control."""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".uv-cache",
    ".uv-python",
    "data",
    "node_modules",
}

IGNORED_FILE_NAMES = {
    ".env",
}

PLACEHOLDER_MARKERS = {
    "your",
    "your-key",
    "your_key",
    "example",
    "placeholder",
    "changeme",
    "xxx",
}

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "authorization": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}"),
    "app_secret": re.compile(r"\bas-[A-Za-z0-9_-]{12,}\b"),
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    kind: str
    redacted: str


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in IGNORED_FILE_NAMES:
            continue
        if any(part in IGNORED_DIRECTORY_NAMES for part in path.parts):
            continue
        yield path


def scan_paths(paths: Iterable[str | Path]) -> list[Finding]:
    findings: list[Finding] = []
    for supplied_path in paths:
        root = Path(supplied_path)
        for path in _iter_files(root):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                for kind, pattern in PATTERNS.items():
                    for match in pattern.finditer(line):
                        value = match.group(0)
                        if _is_placeholder(value):
                            continue
                        findings.append(
                            Finding(
                                path=path,
                                line_number=line_number,
                                kind=kind,
                                redacted=_redact(value),
                            )
                        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Files or directories to scan")
    args = parser.parse_args()

    findings = scan_paths(args.paths)
    for finding in findings:
        print(
            f"{finding.path}:{finding.line_number}: "
            f"{finding.kind}: {finding.redacted}"
        )
    if findings:
        print(f"Secret scan failed: {len(findings)} finding(s).")
        return 1
    print("Secret scan passed: no credentials detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
