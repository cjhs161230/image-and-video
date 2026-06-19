"""Adaptive per-credential concurrency state."""

from dataclasses import dataclass, field


@dataclass
class AdaptiveLimiter:
    max_concurrency: int
    current_limit: int = 1
    available_at: float = 0
    _successes: int = 0
    _server_errors: list[float] = field(default_factory=lambda: list[float]())

    def __post_init__(self) -> None:
        self.current_limit = max(1, min(self.current_limit, self.max_concurrency))

    def record_success(self, *, now: float) -> None:
        self._successes += 1
        self._server_errors = [value for value in self._server_errors if now - value <= 60]
        if (
            self._successes >= 30
            and now >= self.available_at
            and self.current_limit < self.max_concurrency
        ):
            self.current_limit += 1
            self._successes = 0

    def record_rate_limit(self, *, now: float, retry_after: float | None = None) -> None:
        self.current_limit = max(1, self.current_limit // 2)
        self.available_at = now + (retry_after if retry_after is not None else 60)
        self._successes = 0

    def record_server_error(self, *, now: float) -> None:
        self._server_errors = [value for value in self._server_errors if now - value <= 60]
        self._server_errors.append(now)
        if len(self._server_errors) >= 3:
            self.current_limit = max(1, self.current_limit // 2)
            self.available_at = now + 30
            self._server_errors.clear()
            self._successes = 0
