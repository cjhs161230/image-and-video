"""Secure environment secrets and public runtime settings."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_api_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    if len(raw) > 2048:
        raise ValueError("API Base URL 配置无效：长度超过 2048 字符")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("API Base URL 配置无效：必须是 http/https 地址")
    path = parts.path.rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class PublicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ffmpeg_path: str = Field(
        default=r"D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe",
        min_length=1,
    )
    native_download_proxy: str = ""
    matsca_direct_concurrency: int = Field(default=2, ge=1, le=2)
    matsca_native_concurrency: int = Field(default=2, ge=1, le=2)
    cost_rates: dict[str, float] = Field(default_factory=dict)

    @field_validator("native_download_proxy")
    @classmethod
    def validate_native_download_proxy(cls, value: str) -> str:
        proxy = value.strip()
        if not proxy:
            return ""
        if urlsplit(proxy).scheme.lower() not in {"http", "https", "socks5", "socks5h"}:
            raise ValueError("native_download_proxy 只支持 HTTP(S) 或 SOCKS5")
        return proxy

    @field_validator("cost_rates")
    @classmethod
    def validate_cost_rates(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = {"image_per_image", "video_per_frame"}
        if not set(value).issubset(allowed):
            raise ValueError("cost_rates 包含未知费率")
        if any(rate < 0 or not isfinite(rate) for rate in value.values()):
            raise ValueError("cost_rates 必须为有限非负数")
        return value


class SecretSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    dashscope_api_key: str = ""
    matsca_direct_base_url: str = "https://img.matsca.com/v1"
    matsca_direct_api_key: str = ""
    matsca_native_base_url: str = "https://img.matsca.com/v1"
    matsca_native_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    video_feature_enabled: bool = False

    def status(self) -> dict[str, Any]:
        return {
            "dashscope": bool(self.dashscope_api_key),
            "matsca": {
                "direct": bool(self.matsca_direct_api_key),
                "native": bool(self.matsca_native_api_key),
            },
            "deepseek": bool(self.deepseek_api_key),
            "video_feature_enabled": self.video_feature_enabled,
        }


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> PublicSettings:
        if not self.path.exists():
            return PublicSettings()
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return PublicSettings()
        raw = cast(dict[str, Any], loaded)
        raw.pop("matsca_app_concurrency", None)
        for field in ("matsca_direct_concurrency", "matsca_native_concurrency"):
            value = raw.get(field)
            if isinstance(value, int):
                raw[field] = min(max(value, 1), 2)
        return PublicSettings.model_validate(raw)

    def save(self, settings: PublicSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
