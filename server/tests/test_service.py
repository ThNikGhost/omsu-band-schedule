"""ScheduleService: sync behaviour and payload assembly."""

from __future__ import annotations

import datetime as dt

import pytest

from app.errors import NoSnapshotError, UnknownGroupError, UpstreamError
from app.service import ScheduleService
from tests.conftest import NOW

# ------------------------------------------------------------------ syncing


async def test_sync_stores_snapshot_and_state(service: ScheduleService) -> None:
    snapshot = await service.sync_group(5028)
    assert service.store.get(5028) is snapshot
    state = service.store.state(5028)
    assert state.last_success_at is not None
    assert state.consecutive_failures == 0
    assert state.last_error is None


async def test_sync_failure_keeps_previous_snapshot(
    service: ScheduleService, fake_client, snapshot
) -> None:
    """A bad minute at the university must not cost us the data we already have."""
    service.store.put(snapshot)
    fake_client.error = UpstreamError("upstream down")

    with pytest.raises(UpstreamError):
        await service.sync_group(5028)

    assert service.store.get(5028) is snapshot
    state = service.store.state(5028)
    assert state.consecutive_failures == 1
    assert "upstream down" in state.last_error


async def test_consecutive_failures_accumulate(service: ScheduleService, fake_client) -> None:
    fake_client.error = UpstreamError("nope")
    for expected in (1, 2, 3):
        with pytest.raises(UpstreamError):
            await service.sync_group(5028)
        assert service.store.state(5028).consecutive_failures == expected


async def test_sync_rejects_unknown_group(service: ScheduleService) -> None:
    with pytest.raises(UnknownGroupError):
        await service.sync_group(9999)


# ------------------------------------------------------------------ payload


def test_payload_matches_the_contract(loaded_service: ScheduleService) -> None:
    payload = loaded_service.build_payload(5028, days=14, subgroup=None, now=NOW)
    assert payload.v == 1
    assert payload.gid == 5028
    assert payload.g == "МБС-301-О-01"
    assert len(payload.h) == 12
    assert payload.days
    for day in payload.days:
        assert day.l, "days without lessons must not be included"
        assert [x.p for x in day.l] == sorted(x.p for x in day.l)
        for item in day.l:
            assert len(item.n) <= 32


def test_payload_excludes_the_past(loaded_service: ScheduleService) -> None:
    payload = loaded_service.build_payload(5028, days=14, subgroup=None, now=NOW)
    assert all(day.d >= NOW.date().isoformat() for day in payload.days)


def test_payload_respects_the_day_window(loaded_service: ScheduleService) -> None:
    short = loaded_service.build_payload(5028, days=3, subgroup=None, now=NOW)
    long = loaded_service.build_payload(5028, days=14, subgroup=None, now=NOW)
    last_allowed = (NOW.date() + dt.timedelta(days=2)).isoformat()
    assert all(day.d <= last_allowed for day in short.days)
    assert len(short.days) <= len(long.days)


def test_subgroup_filter_keeps_common_lessons(loaded_service: ScheduleService) -> None:
    payload = loaded_service.build_payload(5028, days=21, subgroup=1, now=NOW)
    seen = {item.sg for day in payload.days for item in day.l}
    assert seen <= {None, 1}
    assert None in seen, "lessons for the whole group must stay"
    assert 1 in seen, "the fixture has subgroup lessons in this window"


def test_without_subgroup_everything_is_returned(loaded_service: ScheduleService) -> None:
    payload = loaded_service.build_payload(5028, days=21, subgroup=None, now=NOW)
    seen = {item.sg for day in payload.days for item in day.l}
    assert {1, 2} <= seen


def test_different_subgroups_hash_differently(loaded_service: ScheduleService) -> None:
    one = loaded_service.build_payload(5028, days=21, subgroup=1, now=NOW)
    two = loaded_service.build_payload(5028, days=21, subgroup=2, now=NOW)
    both = loaded_service.build_payload(5028, days=21, subgroup=None, now=NOW)
    assert len({one.h, two.h, both.h}) == 3


def test_hash_ignores_generation_time(loaded_service: ScheduleService) -> None:
    """Otherwise the ETag would change every 3 hours and re-send identical data."""
    later = NOW + dt.timedelta(minutes=30)
    first = loaded_service.build_payload(5028, days=14, subgroup=None, now=NOW)
    second = loaded_service.build_payload(5028, days=14, subgroup=None, now=later)
    assert first.h == second.h
    assert first.gen != second.gen


def test_payload_without_snapshot_raises(service: ScheduleService) -> None:
    with pytest.raises(NoSnapshotError):
        service.build_payload(5028, days=14, subgroup=None, now=NOW)


def test_payload_for_unknown_group_raises(loaded_service: ScheduleService) -> None:
    with pytest.raises(UnknownGroupError):
        loaded_service.build_payload(9999, days=14, subgroup=None, now=NOW)


def test_empty_future_is_a_valid_payload(loaded_service: ScheduleService) -> None:
    """Once the university stops publishing ahead, days is simply empty."""
    far_future = NOW + dt.timedelta(days=400)
    payload = loaded_service.build_payload(5028, days=14, subgroup=None, now=far_future)
    assert payload.days == []
    assert len(payload.h) == 12


# ------------------------------------------------------------- stale, health


def test_fresh_snapshot_is_not_stale(loaded_service: ScheduleService, snapshot) -> None:
    assert loaded_service.is_stale(snapshot, NOW) is False


def test_snapshot_goes_stale_after_two_intervals(loaded_service: ScheduleService, snapshot) -> None:
    assert loaded_service.is_stale(snapshot, NOW + dt.timedelta(hours=5)) is False
    assert loaded_service.is_stale(snapshot, NOW + dt.timedelta(hours=7)) is True


def test_health_reports_per_group(loaded_service: ScheduleService) -> None:
    report = loaded_service.health(now=NOW)
    assert report["status"] == "ok"
    group = report["groups"]["5028"]
    assert group["has_snapshot"] is True
    assert group["group_name"] == "МБС-301-О-01"
    assert group["stale"] is False


def test_health_is_degraded_without_a_snapshot(service: ScheduleService) -> None:
    report = service.health(now=NOW)
    assert report["status"] == "degraded"
    assert report["groups"]["5028"]["has_snapshot"] is False
