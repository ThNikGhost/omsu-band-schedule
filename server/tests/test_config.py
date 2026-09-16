"""Settings loaded the way production loads them: from the environment.

The other tests construct Settings directly with Python lists, which skips
pydantic-settings' env parsing entirely. That gap let a real bug through once:
without NoDecode, a comma-separated GROUPS is fed to json.loads() before any
validator runs, and the app refuses to start.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path: Path):
    """Isolate from the developer's own .env and exported variables."""
    for name in (
        "GROUPS",
        "API_TOKENS",
        "ADMIN_TOKEN",
        "STALE_AFTER_HOURS",
        "FETCH_INTERVAL_HOURS",
        "TZ",
        "DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_csv_groups_are_parsed(monkeypatch) -> None:
    monkeypatch.setenv("GROUPS", "5028,5031")
    assert Settings().groups == [5028, 5031]


def test_csv_tokens_are_parsed(monkeypatch) -> None:
    monkeypatch.setenv("API_TOKENS", "alpha,beta")
    assert Settings().api_tokens == ["alpha", "beta"]


def test_single_value_still_works(monkeypatch) -> None:
    monkeypatch.setenv("GROUPS", "5028")
    assert Settings().groups == [5028]


def test_whitespace_and_trailing_commas_are_tolerated(monkeypatch) -> None:
    monkeypatch.setenv("API_TOKENS", " alpha , beta ,")
    assert Settings().api_tokens == ["alpha", "beta"]


def test_empty_stale_after_hours_falls_back_to_the_interval(monkeypatch) -> None:
    """An unset value in .env arrives as an empty string, not as None."""
    monkeypatch.setenv("STALE_AFTER_HOURS", "")
    monkeypatch.setenv("FETCH_INTERVAL_HOURS", "3")
    assert Settings().stale_after == dt.timedelta(hours=6)


def test_explicit_stale_after_hours_wins(monkeypatch) -> None:
    monkeypatch.setenv("STALE_AFTER_HOURS", "10")
    assert Settings().stale_after == dt.timedelta(hours=10)


def test_now_is_timezone_aware() -> None:
    moment = Settings(tz="Asia/Omsk").now()
    assert moment.tzinfo is not None
    assert moment.utcoffset() == dt.timedelta(hours=6)


def test_snapshot_window_covers_past_and_future() -> None:
    settings = Settings(ics_past_days=14, days_ahead_max=21)
    start, end = settings.snapshot_window(dt.date(2026, 9, 16))
    assert start == dt.date(2026, 9, 2)
    assert end == dt.date(2026, 10, 21)


def test_example_env_file_is_loadable(monkeypatch) -> None:
    """.env.example must stay in sync with the field names."""
    example = Path(__file__).resolve().parent.parent / ".env.example"
    settings = Settings(_env_file=example)
    assert settings.groups == [5028]
    assert len(settings.api_tokens) == 2
    assert settings.tz == "Asia/Omsk"
