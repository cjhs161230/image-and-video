import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from image_video.infrastructure.config import (
    PublicSettings,
    SecretSettings,
    SettingsStore,
    normalize_api_base_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://img.matsca.com", "https://img.matsca.com/v1"),
        ("https://img.matsca.com/", "https://img.matsca.com/v1"),
        ("https://img.matsca.com/v1", "https://img.matsca.com/v1"),
        ("https://img.matsca.com/v1/", "https://img.matsca.com/v1"),
    ],
)
def test_normalize_api_base_url_avoids_duplicate_v1(raw: str, expected: str) -> None:
    assert normalize_api_base_url(raw) == expected


def test_public_settings_rejects_secret_fields() -> None:
    with pytest.raises(ValidationError):
        PublicSettings.model_validate(
            {"ffmpeg_path": "D:/ffmpeg/ffmpeg.exe", "api_key": "not-allowed"}
        )


def test_settings_store_persists_only_public_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = PublicSettings(
        ffmpeg_path="D:/ffmpeg/ffmpeg.exe",
        native_download_proxy="http://127.0.0.1:7890",
    )

    store.save(settings)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["ffmpeg_path"] == "D:/ffmpeg/ffmpeg.exe"
    assert persisted["native_download_proxy"] == "http://127.0.0.1:7890"
    assert "api_key" not in persisted


def test_secret_status_reports_presence_without_exposing_values() -> None:
    secrets = SecretSettings(
        dashscope_api_key="dash-secret",
        matsca_direct_api_key="direct-secret",
        deepseek_api_key="deep-secret",
    )

    assert secrets.status() == {
        "dashscope": True,
        "matsca": {"app": False, "direct": True, "native": False},
        "deepseek": True,
    }

