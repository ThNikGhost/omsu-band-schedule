"""Application settings, loaded from environment / .env."""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_BELLS = _REPO_ROOT.parent / "shared" / "bells.json"


def _split_csv(value: object) -> object:
    """Accept both "a,b" and ["a", "b"] for list-valued settings."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # NoDecode is required: without it pydantic-settings tries json.loads() on
    # the raw env value before any validator runs, so "5028,5031" explodes.
    groups: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [5028])
    api_tokens: Annotated[list[str], NoDecode] = Field(default_factory=list)
    admin_token: str = ""

    fetch_interval_hours: int = Field(default=3, ge=1, le=24)
    days_ahead_max: int = Field(default=21, ge=1, le=90)
    ics_past_days: int = Field(default=14, ge=0, le=180)
    stale_after_hours: int | None = None

    tz: str = "Asia/Omsk"
    data_dir: Path = Path("data")
    bells_path: Path = _DEFAULT_BELLS
    abbreviations_path: Path = _REPO_ROOT / "abbreviations.yaml"

    upstream_base: str = "https://eservice.omsu.ru/schedule/backend"
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 60.0
    upstream_dict_timeout: float = 120.0
    max_response_bytes: int = 16 * 1024 * 1024

    rate_limit_per_minute: int = Field(default=60, ge=1)
    log_level: str = "INFO"

    @field_validator("groups", "api_tokens", mode="before")
    @classmethod
    def _accept_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("stale_after_hours", mode="before")
    @classmethod
    def _empty_means_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def stale_after(self) -> dt.timedelta:
        """Age at which a snapshot is reported as stale. Default: two missed cycles."""
        hours = self.stale_after_hours or self.fetch_interval_hours * 2
        return dt.timedelta(hours=hours)

    @property
    def fetch_interval(self) -> dt.timedelta:
        return dt.timedelta(hours=self.fetch_interval_hours)

    def now(self) -> dt.datetime:
        """The single source of 'now'. Never use datetime.now() without a tz."""
        return dt.datetime.now(self.tzinfo)

    def snapshot_window(self, today: dt.date) -> tuple[dt.date, dt.date]:
        """Date range kept on disk: the API feed plus a past tail for the .ics feed."""
        return (
            today - dt.timedelta(days=self.ics_past_days),
            today + dt.timedelta(days=self.days_ahead_max + 14),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
