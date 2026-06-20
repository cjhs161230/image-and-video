"""Secure environment secrets and public runtime settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_api_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class PublicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ffmpeg_path: str = r"D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"
    native_download_proxy: str = ""
    matsca_app_concurrency: int = Field(default=1, ge=1, le=1)
    matsca_direct_concurrency: int = Field(default=5, ge=1, le=5)
    matsca_native_concurrency: int = Field(default=50, ge=1, le=50)
    cost_rates: dict[str, float] = Field(default_factory=dict)


class SecretSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    dashscope_api_key: str = ""
    matsca_app_base_url: str = "https://img.matsca.com/v1"
    matsca_app_api_key: str = ""
    matsca_app_id: str = ""
    matsca_app_secret: str = ""
    matsca_direct_base_url: str = "https://img.matsca.com/v1"
    matsca_direct_api_key: str = ""
    matsca_native_base_url: str = "https://img.matsca.com/v1"
    matsca_native_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"

    def status(self) -> dict[str, Any]:
        return {
            "dashscope": bool(self.dashscope_api_key),
            "matsca": {
                "app": bool(
                    self.matsca_app_api_key
                    and self.matsca_app_id
                    and self.matsca_app_secret
                ),
                "direct": bool(self.matsca_direct_api_key),
                "native": bool(self.matsca_native_api_key),
            },
            "deepseek": bool(self.deepseek_api_key),
        }


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> PublicSettings:
        if not self.path.exists():
            return PublicSettings()
        return PublicSettings.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, settings: PublicSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
