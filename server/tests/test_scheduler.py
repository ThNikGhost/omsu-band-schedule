"""SyncScheduler decision logic.

Only _should_fetch and the crash-resistance of the loop are tested; the sleeping
itself is not, since that would just be testing asyncio.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.errors import UpstreamError
from app.models import GroupState
from app.scheduler import BACKOFF_BASE_SECONDS, SyncScheduler
from app.service import ScheduleService
from tests.conftest import NOW


@pytest.fixture
def scheduler(service: ScheduleService, settings) -> SyncScheduler:
    return SyncScheduler(service, settings)


def test_fetches_when_there_is_no_snapshot(scheduler: SyncScheduler) -> None:
    assert scheduler._should_fetch(5028, NOW) is True


def test_skips_a_fresh_snapshot(scheduler: SyncScheduler, snapshot) -> None:
    """Survives `restart: unless-stopped` without re-downloading 1.5 MB."""
    scheduler.service.store.put(snapshot)
    assert scheduler._should_fetch(5028, NOW + dt.timedelta(minutes=30)) is False


def test_fetches_once_the_interval_has_passed(scheduler: SyncScheduler, snapshot) -> None:
    scheduler.service.store.put(snapshot)
    assert scheduler._should_fetch(5028, NOW + dt.timedelta(hours=3, minutes=1)) is True


def test_backoff_delays_the_next_attempt(scheduler: SyncScheduler, snapshot) -> None:
    scheduler.service.store.put(snapshot)
    scheduler.service.store.set_state(
        GroupState(group_id=5028, last_attempt_at=NOW, consecutive_failures=1)
    )
    # First backoff step is 5 minutes.
    assert scheduler._should_fetch(5028, NOW + dt.timedelta(seconds=60)) is False
    assert (
        scheduler._should_fetch(5028, NOW + dt.timedelta(seconds=BACKOFF_BASE_SECONDS + 1)) is True
    )


def test_backoff_grows_with_failures(scheduler: SyncScheduler, snapshot) -> None:
    scheduler.service.store.put(snapshot)
    scheduler.service.store.set_state(
        GroupState(group_id=5028, last_attempt_at=NOW, consecutive_failures=3)
    )
    # Third failure means 20 minutes, not 5.
    assert scheduler._should_fetch(5028, NOW + dt.timedelta(minutes=10)) is False
    assert scheduler._should_fetch(5028, NOW + dt.timedelta(minutes=21)) is True


def test_backoff_never_exceeds_the_interval(scheduler: SyncScheduler, snapshot) -> None:
    scheduler.service.store.put(snapshot)
    scheduler.service.store.set_state(
        GroupState(group_id=5028, last_attempt_at=NOW, consecutive_failures=99)
    )
    assert scheduler._should_fetch(5028, NOW + dt.timedelta(hours=3, minutes=1)) is True


async def test_cycle_survives_a_failing_upstream(scheduler: SyncScheduler, fake_client) -> None:
    """One failed group must not stop the cycle or kill the task."""
    fake_client.error = UpstreamError("down")
    await scheduler._sync_once()
    assert scheduler.service.store.state(5028).consecutive_failures == 1


async def test_start_and_stop(scheduler: SyncScheduler) -> None:
    await scheduler.start()
    assert scheduler._task is not None
    await asyncio.sleep(0)
    await scheduler.stop()
    assert scheduler._task is None


def test_poll_delay_is_never_shorter_than_a_minute(scheduler: SyncScheduler) -> None:
    for _ in range(20):
        assert scheduler._next_delay() >= 60.0
