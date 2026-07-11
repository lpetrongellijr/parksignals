"""Runtime configuration for the ParkSignals public API."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    version: str = os.getenv("PARKSIGNALS_API_VERSION", "1.0")
    environment: str = os.getenv("PARKSIGNALS_API_ENV", "local")
    public_api_base_url: str = os.getenv("PARKSIGNALS_PUBLIC_API_BASE_URL", "https://parksignals-api.onrender.com").rstrip("/")
    data_dir: Path = Path(os.getenv("PARKSIGNALS_DATA_DIR", ROOT_DIR / "public" / "data"))
    cache_ttl_seconds: int = _int_env("PARKSIGNALS_API_CACHE_TTL_SECONDS", 30)
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("PARKSIGNALS_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    )
    api_key_required: bool = _bool_env("PARKSIGNALS_API_KEY_REQUIRED", False)
    api_key: str = os.getenv("PARKSIGNALS_API_KEY", "")


settings = Settings()
