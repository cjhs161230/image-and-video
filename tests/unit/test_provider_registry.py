from image_video.infrastructure.providers.registry import LimiterRegistry


def test_registry_shares_limiter_for_same_credential_and_mode() -> None:
    registry = LimiterRegistry()

    first = registry.get("credential-a", "direct", max_concurrency=5)
    second = registry.get("credential-a", "direct", max_concurrency=5)
    other = registry.get("credential-b", "direct", max_concurrency=5)

    assert first is second
    assert first is not other
    assert first.max_concurrency == 5

