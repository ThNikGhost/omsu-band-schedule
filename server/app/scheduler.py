"""Background sync loop.

A plain asyncio task rather than APScheduler: there is one job, and the two
behaviours that actually matter here - skip the fetch when the snapshot on disk
is still fresh (so `restart: unless-stopped` does not hammer the university),
and back off on repeated failures - are less code this way than as APScheduler
configuration.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import random

from app.config import Settings
from app.service import ScheduleService

logger = logging.getLogger(__name__)

# Backoff after consecutive failures: 5, 10, 20, 40 min, capped at the interval.
BACKOFF_BASE_SECONDS = 300
MAX_BACKOFF_EXPONENT = 6
# Pause between groups so we never hold two 1.5 MB transfers at once.
GROUP_STAGGER_SECONDS = 2.0
INTERVAL_JITTER = 0.05


class SyncScheduler:
    def __init__(self, service: ScheduleService, settings: Settings) -> None:
        self.service = service
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="schedule-sync")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._sync_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # The loop must never die: a dead scheduler is a silently frozen
                # snapshot that only /health would reveal.
                logger.exception("sync cycle crashed, continuing")
            await asyncio.sleep(self._next_delay())

    async def _sync_once(self) -> None:
        now = self.settings.now()
        for index, group_id in enumerate(self.settings.groups):
            if index:
                await asyncio.sleep(GROUP_STAGGER_SECONDS)

            if not self._should_fetch(group_id, now):
                continue

            try:
                await self.service.sync_group(group_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("group %s skipped this cycle: %s", group_id, exc)
                continue

    def _should_fetch(self, group_id: int, now: dt.datetime) -> bool:
        snapshot = self.service.store.get(group_id)
        state = self.service.store.state(group_id)

        if snapshot is None:
            return True

        age = (now - snapshot.fetched_at).total_seconds()
        if state.consecutive_failures:
            wait = min(
                BACKOFF_BASE_SECONDS
                * 2 ** min(state.consecutive_failures - 1, MAX_BACKOFF_EXPONENT),
                self.settings.fetch_interval.total_seconds(),
            )
            last_attempt = state.last_attempt_at
            return last_attempt is None or (now - last_attempt).total_seconds() >= wait

        return age >= self.settings.fetch_interval.total_seconds()

    def _next_delay(self) -> float:
        """Poll often enough for backoff to fire, but never faster than 1 minute."""
        interval = self.settings.fetch_interval.total_seconds()
        base = min(interval, BACKOFF_BASE_SECONDS)
        jitter = 1.0 + INTERVAL_JITTER * (2.0 * random.random() - 1.0)  # noqa: S311 - not crypto
        return max(60.0, base * jitter)
