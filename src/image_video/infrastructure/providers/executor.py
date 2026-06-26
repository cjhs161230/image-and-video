"""Credential-scoped execution gate and classified provider retries."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TypeVar

import httpx

from image_video.infrastructure.logging import JsonlLogger
from image_video.infrastructure.providers.limiter import AdaptiveLimiter

T = TypeVar("T")


class CredentialGate:
    def __init__(self, limiter: AdaptiveLimiter):
        self.limiter = limiter
        self._active = 0
        self._condition = threading.Condition()
        self._local = threading.local()

    @contextmanager
    def slot(self) -> Generator[None]:
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return
        with self._condition:
            while self._active >= self.limiter.current_limit:
                self._condition.wait()
            self._active += 1
            self._local.depth = 1
        try:
            yield
        finally:
            with self._condition:
                self._local.depth = 0
                self._active -= 1
                self._condition.notify_all()


class ProviderRequestExecutor:
    def __init__(
        self,
        *,
        gate: CredentialGate,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = lambda: random.uniform(0.2, 0.8),
        clock: Callable[[], float] = time.time,
        logger: JsonlLogger | None = None,
        provider: str = "provider",
    ):
        self.gate = gate
        self.sleep = sleep
        self.jitter = jitter
        self.clock = clock
        self.logger = logger
        self.provider = provider

    def run(self, operation: Callable[[], T], *, request_id: str = "provider") -> T:
        rate_limit_retries = 0
        server_retries = 0
        connection_retries = 0
        attempt = 0
        while True:
            attempt += 1
            delay = self.jitter()
            if delay > 0:
                self.sleep(delay)
            try:
                with self.gate.slot():
                    result = operation()
            except httpx.TimeoutException:
                raise
            except httpx.ConnectError:
                if connection_retries >= 2:
                    raise
                connection_retries += 1
                self.sleep(2 ** (connection_retries - 1))
                continue
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                now = self.clock()
                if status == 429:
                    retry_after = _retry_after_seconds(exc.response)
                    self.gate.limiter.record_rate_limit(
                        now=now, retry_after=retry_after
                    )
                    if rate_limit_retries >= 3:
                        raise
                    rate_limit_retries += 1
                    self.sleep(retry_after)
                    continue
                if status >= 500:
                    self.gate.limiter.record_server_error(now=now)
                    if server_retries >= 2:
                        raise
                    server_retries += 1
                    self.sleep(2 ** (server_retries - 1))
                    continue
                raise
            self.gate.limiter.record_success(now=self.clock())
            if self.logger is not None:
                self.logger.write(
                    level="info",
                    event="provider_request_succeeded",
                    request_id=request_id,
                    data={"provider": self.provider, "attempt": attempt},
                )
            return result


def _retry_after_seconds(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            pass
    return 60
