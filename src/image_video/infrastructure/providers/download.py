"""Remote image download with an optional native-mode proxy."""

from __future__ import annotations

from collections.abc import Callable

import httpx

ClientFactory = Callable[[str | None], httpx.Client]


def default_client_factory(proxy: str | None) -> httpx.Client:
    return httpx.Client(proxy=proxy, timeout=120)


def download_image(
    url: str,
    *,
    proxy: str | None = None,
    client_factory: ClientFactory = default_client_factory,
) -> bytes:
    with client_factory(proxy) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content

