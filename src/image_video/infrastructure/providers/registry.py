"""Credential-scoped limiter registry shared by all jobs."""

import threading

from image_video.infrastructure.providers.limiter import AdaptiveLimiter


class LimiterRegistry:
    def __init__(self) -> None:
        self._limiters: dict[tuple[str, str], AdaptiveLimiter] = {}
        self._lock = threading.Lock()

    def get(
        self, credential_id: str, mode: str, *, max_concurrency: int
    ) -> AdaptiveLimiter:
        key = (credential_id, mode)
        with self._lock:
            limiter = self._limiters.get(key)
            if limiter is None:
                limiter = AdaptiveLimiter(max_concurrency=max_concurrency)
                self._limiters[key] = limiter
            return limiter

