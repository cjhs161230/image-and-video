"""Credential-scoped execution gate and classified provider retries."""

from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypeVar

import httpx

from image_video.infrastructure.logging import JsonlLogger, redact_sensitive
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

    def run(
        self,
        operation: Callable[[], T],
        *,
        request_id: str = "provider",
        metadata: dict[str, Any] | None = None,
    ) -> T:
        rate_limit_retries = 0
        server_retries = 0
        connection_retries = 0
        attempt = 0
        while True:
            attempt += 1
            delay = self.jitter()
            if delay > 0:
                self.sleep(delay)
            started_at = self.clock()
            if metadata is not None:
                self._log(
                    level="info",
                    event="provider_request_started",
                    request_id=request_id,
                    data={"attempt": attempt, **metadata},
                )
            try:
                with self.gate.slot():
                    result = operation()
            except httpx.TimeoutException as exc:
                self._log_failure(
                    exc,
                    request_id=request_id,
                    attempt=attempt,
                    started_at=started_at,
                    metadata=metadata,
                )
                raise
            except httpx.ConnectError as exc:
                if connection_retries >= 2:
                    self._log_failure(
                        exc,
                        request_id=request_id,
                        attempt=attempt,
                        started_at=started_at,
                        metadata=metadata,
                    )
                    raise
                self._log_failure(
                    exc,
                    request_id=request_id,
                    attempt=attempt,
                    started_at=started_at,
                    metadata=metadata,
                )
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
                        self._log_failure(
                            exc,
                            request_id=request_id,
                            attempt=attempt,
                            started_at=started_at,
                            metadata=metadata,
                        )
                        raise
                    self._log_failure(
                        exc,
                        request_id=request_id,
                        attempt=attempt,
                        started_at=started_at,
                        metadata=metadata,
                    )
                    rate_limit_retries += 1
                    self.sleep(retry_after)
                    continue
                if status >= 500:
                    self.gate.limiter.record_server_error(now=now)
                    if server_retries >= 2:
                        self._log_failure(
                            exc,
                            request_id=request_id,
                            attempt=attempt,
                            started_at=started_at,
                            metadata=metadata,
                        )
                        raise
                    self._log_failure(
                        exc,
                        request_id=request_id,
                        attempt=attempt,
                        started_at=started_at,
                        metadata=metadata,
                    )
                    server_retries += 1
                    self.sleep(2 ** (server_retries - 1))
                    continue
                self._log_failure(
                    exc,
                    request_id=request_id,
                    attempt=attempt,
                    started_at=started_at,
                    metadata=metadata,
                )
                raise
            except Exception as exc:
                self._log_failure(
                    exc,
                    request_id=request_id,
                    attempt=attempt,
                    started_at=started_at,
                    metadata=metadata,
                )
                raise
            self.gate.limiter.record_success(now=self.clock())
            success_data: dict[str, Any] = {
                "attempt": attempt,
                **(metadata or {}),
                "elapsed_ms": self._elapsed_ms(started_at),
            }
            if isinstance(result, httpx.Response):
                success_data["http_status"] = result.status_code
            self._log(
                level="info",
                event="provider_request_succeeded",
                request_id=request_id,
                data=success_data,
            )
            return result

    def _log(
        self,
        *,
        level: str,
        event: str,
        request_id: str,
        data: dict[str, Any],
    ) -> None:
        if self.logger is None:
            return
        if "provider" not in data:
            data = {"provider": self.provider, **data}
        self.logger.write(
            level=level,
            event=event,
            request_id=request_id,
            data=data,
        )

    def _log_failure(
        self,
        exc: Exception,
        *,
        request_id: str,
        attempt: int,
        started_at: float,
        metadata: dict[str, Any] | None,
    ) -> None:
        if metadata is None:
            return
        data: dict[str, Any] = {
            "attempt": attempt,
            **metadata,
            "elapsed_ms": self._elapsed_ms(started_at),
            "exception_type": type(exc).__name__,
            "error_message": _safe_exception_message(exc),
        }
        if isinstance(exc, httpx.HTTPStatusError):
            data["http_status"] = exc.response.status_code
        self._log(
            level="error",
            event="provider_request_failed",
            request_id=request_id,
            data=data,
        )

    def _elapsed_ms(self, started_at: float) -> int:
        return max(0, int((self.clock() - started_at) * 1000))


def _retry_after_seconds(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            pass
    return 60


def _safe_exception_message(exc: Exception) -> str:
    detail = str(exc).strip()
    if not detail:
        return "provider request failed"
    redacted = redact_sensitive(detail)
    if not isinstance(redacted, str):
        return "provider request failed"
    without_urls = re.sub(r"https?://\S+", "[url]", redacted)
    if len(without_urls) > 500:
        without_urls = f"{without_urls[:500]}..."
    return without_urls
