"""Shared fixtures.

Everything runs against the real API response captured on 2026-09-16
(tests/data/omsu_group_5028.json), so the parsers are exercised by the actual
mess the university emits rather than by hand-written ideal input.

"Now" is always injected, never read from the clock, so no freezegun is needed.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.bells import Bells
from app.config import Settings
from app.normalize.lesson import normalize_response
from app.normalize.subject import Abbreviator
from app.service import ScheduleService
from app.store import SnapshotStore

DATA = Path(__file__).parent / "data"
REPO = Path(__file__).resolve().parent.parent.parent
SHARED = REPO / "shared"
SERVER = REPO / "server"

OMSK = ZoneInfo("Asia/Omsk")

# The day the fixture was captured. The feed has lessons on and after this date.
NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=OMSK)

TOKEN = "test-token-one"
OTHER_TOKEN = "test-token-two"
ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def now() -> dt.datetime:
    return NOW


@pytest.fixture
def api_payload() -> dict[str, Any]:
    return json.loads((DATA / "omsu_group_5028.json").read_text(encoding="utf-8"))


@pytest.fixture
def distinct() -> dict[str, Any]:
    return json.loads((DATA / "omsu_distinct_values.json").read_text(encoding="utf-8"))


class FrozenSettings(Settings):
    """Settings with a pinned clock.

    Every date-dependent code path reads Settings.now(), so freezing it here is
    enough to make the whole app deterministic - no freezegun, no patching of
    datetime. Tests that need a different moment assign to `frozen_now`.
    """

    frozen_now: dt.datetime = NOW

    def now(self) -> dt.datetime:
        return self.frozen_now


@pytest.fixture
def settings(tmp_path: Path) -> FrozenSettings:
    return FrozenSettings(
        groups=[5028],
        api_tokens=[TOKEN, OTHER_TOKEN],
        admin_token=ADMIN_TOKEN,
        data_dir=tmp_path / "data",
        bells_path=SHARED / "bells.json",
        abbreviations_path=SERVER / "abbreviations.yaml",
        tz="Asia/Omsk",
        fetch_interval_hours=3,
        days_ahead_max=21,
        ics_past_days=14,
    )


@pytest.fixture
def bells(settings: Settings) -> Bells:
    return Bells.load(settings.bells_path)


@pytest.fixture
def abbreviator(settings: Settings) -> Abbreviator:
    return Abbreviator.from_yaml(settings.abbreviations_path)


@pytest.fixture
def store(settings: Settings) -> SnapshotStore:
    store = SnapshotStore(settings.data_dir)
    store.load_all(settings.groups)
    return store


@pytest.fixture
def snapshot(settings: Settings, api_payload: dict[str, Any], now: dt.datetime):
    return normalize_response(
        api_payload,
        group_id=5028,
        window=settings.snapshot_window(now.date()),
        fetched_at=now,
    )


class FakeClient:
    """Stand-in for OmsuClient. Returns a payload or raises whatever it was given."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    async def fetch_group(self, group_id: int) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload

    async def fetch_dict(self, kind: str) -> Any:
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.fixture
def fake_client(api_payload: dict[str, Any]) -> FakeClient:
    return FakeClient(payload=api_payload)


@pytest.fixture
def service(
    settings: Settings,
    store: SnapshotStore,
    fake_client: FakeClient,
    abbreviator: Abbreviator,
    bells: Bells,
) -> ScheduleService:
    return ScheduleService(settings, store, fake_client, abbreviator, bells)


@pytest.fixture
def loaded_service(service: ScheduleService, snapshot) -> ScheduleService:
    """A service that already has a snapshot, as if a sync had happened."""
    service.store.put(snapshot)
    return service
