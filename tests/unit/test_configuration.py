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


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "img.matsca.com/v1",
        "ftp://img.matsca.com/v1",
        "data:image/png;base64,aW1hZ2U=",
        f"https://img.matsca.com/{'a' * 2100}",
    ],
)
def test_normalize_api_base_url_rejects_invalid_base_urls(raw: str) -> None:
    with pytest.raises(ValueError, match="API Base URL"):
        normalize_api_base_url(raw)


def test_public_settings_rejects_secret_fields() -> None:
    with pytest.raises(ValidationError):
        PublicSettings.model_validate(
            {"ffmpeg_path": "D:/ffmpeg/ffmpeg.exe", "api_key": "not-allowed"}
        )


@pytest.mark.parametrize(
    "values",
    [
        {"ffmpeg_path": ""},
        {"native_download_proxy": "file:///tmp/proxy"},
        {"cost_rates": {"unknown": 1}},
        {"cost_rates": {"image_per_image": -1}},
    ],
)
def test_public_settings_rejects_invalid_runtime_values(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PublicSettings.model_validate(values)


def test_settings_store_persists_only_public_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = PublicSettings(
        ffmpeg_path="D:/ffmpeg/ffmpeg.exe",
        native_download_proxy="http://127.0.0.1:7890",
        cost_rates={"image_per_image": 2.5, "video_per_frame": 1.5},
    )

    store.save(settings)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["ffmpeg_path"] == "D:/ffmpeg/ffmpeg.exe"
    assert persisted["native_download_proxy"] == "http://127.0.0.1:7890"
    assert persisted["cost_rates"] == {
        "image_per_image": 2.5,
        "video_per_frame": 1.5,
    }
    assert "api_key" not in persisted


def test_settings_store_ignores_deprecated_app_fields_and_drops_them_on_save(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "ffmpeg_path": "D:/ffmpeg/ffmpeg.exe",
                "matsca_app_concurrency": 1,
                "matsca_direct_concurrency": 5,
                "matsca_native_concurrency": 50,
            }
        ),
        encoding="utf-8",
    )
    store = SettingsStore(path)

    settings = store.load()
    store.save(settings)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert settings.matsca_direct_concurrency == 2
    assert settings.matsca_native_concurrency == 2
    assert "matsca_app_concurrency" not in persisted


def test_secret_status_reports_presence_without_exposing_values() -> None:
    secrets = SecretSettings(
        dashscope_api_key="dash-secret",
        matsca_direct_api_key="direct-secret",
        matsca_native_api_key="",
        deepseek_api_key="deep-secret",
    )

    assert secrets.status() == {
        "dashscope": True,
        "matsca": {"direct": True, "native": False},
        "deepseek": True,
        "video_feature_enabled": False,
    }
    assert not any(name.startswith("matsca_app_") for name in SecretSettings.model_fields)
