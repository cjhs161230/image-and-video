"""Worker-level recoverable errors."""

from __future__ import annotations


class RecoverableImageRetrievalError(RuntimeError):
    def __init__(self, *, error_code: str, error_message: str):
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
