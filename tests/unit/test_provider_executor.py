import json
import threading
from pathlib import Path

import httpx
import pytest

from image_video.infrastructure.logging import JsonlLogger
from image_video.infrastructure.providers.executor import (
    CredentialGate,
    ProviderRequestExecutor,
)
from image_video.infrastructure.providers.limiter import AdaptiveLimiter


def response_error(status: int, retry_after: str | None = None) -> httpx.HTTPStatusError:
    headers = {"Retry-After": retry_after} if retry_after else {}
    request = httpx.Request("POST", "https://provider.test")
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError("failed", request=request, response=response)


def test_timeout_is_not_retried() -> None:
    attempts = 0
    executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=5)),
        sleep=lambda _: None,
        jitter=lambda: 0,
    )

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("uncertain")

    with pytest.raises(httpx.ReadTimeout):
        executor.run(operation)

    assert attempts == 1


def test_rate_limit_retries_three_times_then_succeeds() -> None:
    attempts = 0
    sleeps: list[float] = []
    executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=5)),
        sleep=sleeps.append,
        jitter=lambda: 0.25,
    )

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            raise response_error(429, "2")
        return "ok"

    assert executor.run(operation) == "ok"
    assert attempts == 4
    assert 2 in sleeps
    assert 0.25 in sleeps


def test_server_error_retries_twice_then_raises() -> None:
    attempts = 0
    executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=5)),
        sleep=lambda _: None,
        jitter=lambda: 0,
    )

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise response_error(502)

    with pytest.raises(httpx.HTTPStatusError):
        executor.run(operation)

    assert attempts == 3


def test_credential_gate_never_exceeds_current_limit() -> None:
    limiter = AdaptiveLimiter(max_concurrency=5, current_limit=1)
    gate = CredentialGate(limiter)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with gate.slot():
            first_entered.set()
            release_first.wait(timeout=2)

    def second() -> None:
        first_entered.wait(timeout=2)
        with gate.slot():
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()

    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    assert second_entered.wait(timeout=2)
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)


def test_credential_gate_allows_reentrant_slot_on_same_thread() -> None:
    gate = CredentialGate(AdaptiveLimiter(max_concurrency=2, current_limit=1))

    with gate.slot(), gate.slot():
        assert gate.limiter.current_limit == 1


def test_provider_executor_writes_structured_success_event(tmp_path: Path) -> None:
    log_path = tmp_path / "provider.jsonl"
    executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=2)),
        sleep=lambda _: None,
        jitter=lambda: 0,
        logger=JsonlLogger(log_path),
        provider="matsca",
    )

    assert executor.run(lambda: "ok", request_id="task-1") == "ok"

    [record] = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert record["event"] == "provider_request_succeeded"
    assert record["request_id"] == "task-1"
    assert record["data"] == {"provider": "matsca", "attempt": 1}
