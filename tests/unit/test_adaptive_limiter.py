from image_video.infrastructure.providers.limiter import AdaptiveLimiter


def test_limiter_starts_at_one_and_ramps_after_thirty_successes() -> None:
    limiter = AdaptiveLimiter(max_concurrency=5)

    for _ in range(29):
        limiter.record_success(now=0)
    assert limiter.current_limit == 1

    limiter.record_success(now=0)
    assert limiter.current_limit == 2


def test_limiter_halves_on_rate_limit_and_honors_cooldown() -> None:
    limiter = AdaptiveLimiter(max_concurrency=50, current_limit=20)

    limiter.record_rate_limit(now=100, retry_after=45)

    assert limiter.current_limit == 10
    assert limiter.available_at == 145


def test_three_server_errors_halve_limit() -> None:
    limiter = AdaptiveLimiter(max_concurrency=10, current_limit=8)

    limiter.record_server_error(now=1)
    limiter.record_server_error(now=20)
    limiter.record_server_error(now=40)

    assert limiter.current_limit == 4
    assert limiter.available_at == 70

