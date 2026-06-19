"""Credential-scoped execution gate and classified provider retries."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TypeVar

import httpx

from image_video.infrastructure.providers.limiter import AdaptiveLimiter

T = TypeVar("T")


class CredentialGate:
    def __init__(self, limiter: AdaptiveLimiter):
        self.limiter = limiter
        self._active = 0
        self._condition = threading.Condition()

    @contextmanager
    def slot(self) -> Generator[None]:
        with self._condition:
            while self._active >= self.limiter.current_limit:
                self._condition.wait()
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
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
    ):
        self.gate = gate
        self.sleep = sleep
        self.jitter = jitter
        self.clock = clock

    def run(self, operation: Callable[[], T]) -> T:
        rate_limit_retries = 0
        server_retries = 0
        connection_retries = 0
        while True:
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
            return result


def _retry_after_seconds(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            pass
    return 60
