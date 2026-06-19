"""Structured logging helpers with recursive secret redaction."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "app_secret",
    "authorization",
    "password",
    "private_key",
    "token",
}
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]+")


def redact_sensitive(value: Any, *, key: str | None = None) -> Any:
    if key and key.lower() in SENSITIVE_KEYS:
        return "***"
    if isinstance(value, str):
        return BEARER_PATTERN.sub("Bearer ***", value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(item_key): redact_sensitive(item_value, key=str(item_key))
            for item_key, item_value in mapping.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        return [redact_sensitive(item) for item in sequence]
    return value


class JsonlLogger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def write(
        self,
        *,
        level: str,
        event: str,
        request_id: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": level.upper(),
            "event": event,
            "request_id": request_id,
            "data": redact_sensitive(dict(data or {})),
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
