"""Fetching, and turning a snapshot into a wire response."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

from app.bells import Bells
from app.config import Settings
from app.errors import NoSnapshotError, UnknownGroupError
from app.hashing import payload_hash
from app.models import DayOut, GroupState, Lesson, LessonOut, ScheduleOut, Snapshot
from app.normalize.lesson import normalize_response
from app.normalize.subject import Abbreviator
from app.store import SnapshotStore
from app.upstream.omsu import OmsuClient

logger = logging.getLogger(__name__)


class ScheduleService:
    def __init__(
        self,
        settings: Settings,
        store: SnapshotStore,
        client: OmsuClient,
        abbreviator: Abbreviator,
        bells: Bells,
    ) -> None:
        self.settings = settings
        self.store = store
        self.client = client
        self.abbreviate = abbreviator
        self.bells = bells
        self._locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------ fetch

    def _lock(self, group_id: int) -> asyncio.Lock:
        return self._locks.setdefault(group_id, asyncio.Lock())

    async def sync_group(self, group_id: int) -> Snapshot:
        """Fetch, normalise and persist one group. Single-flight per group.

        On failure the previous snapshot is left untouched: serving slightly old
        data beats serving nothing because the university API had a bad minute.
        """
        self.require_known(group_id)

        async with self._lock(group_id):
            now = self.settings.now()
            state = self.store.state(group_id).model_copy(
                update={"last_attempt_at": now},
            )
            try:
                payload = await self.client.fetch_group(group_id)
                snapshot = normalize_response(
                    payload,
                    group_id=group_id,
                    window=self.settings.snapshot_window(now.date()),
                    fetched_at=now,
                )
            except Exception as exc:
                state = state.model_copy(
                    update={
                        "last_error": f"{type(exc).__name__}: {exc}",
                        "consecutive_failures": state.consecutive_failures + 1,
                    }
                )
                self.store.set_state(state)
                logger.warning(
                    "sync failed for group %s (failure #%d): %s",
                    group_id,
                    state.consecutive_failures,
                    exc,
                )
                raise

            self.store.put(snapshot)
            self.store.set_state(
                GroupState(
                    group_id=group_id,
                    last_attempt_at=now,
                    last_success_at=now,
                    last_error=None,
                    consecutive_failures=0,
                )
            )
            logger.info(
                "synced group %s: %d lessons in window, %d skipped, %d upstream days",
                group_id,
                len(snapshot.lessons),
                snapshot.skipped,
                snapshot.upstream_days,
            )
            return snapshot

    # ----------------------------------------------------------------- lookup

    def require_known(self, group_id: int) -> None:
        if group_id not in self.settings.groups:
            raise UnknownGroupError(group_id)

    def require_snapshot(self, group_id: int) -> Snapshot:
        self.require_known(group_id)
        snapshot = self.store.get(group_id)
        if snapshot is None:
            raise NoSnapshotError(group_id)
        return snapshot

    def is_stale(self, snapshot: Snapshot, now: dt.datetime) -> bool:
        return (now - snapshot.fetched_at) > self.settings.stale_after

    # ---------------------------------------------------------------- payload

    def build_payload(
        self,
        group_id: int,
        *,
        days: int,
        subgroup: int | None,
        now: dt.datetime | None = None,
    ) -> ScheduleOut:
        """Wire response for one group, already filtered and abbreviated."""
        snapshot = self.require_snapshot(group_id)
        moment = now or self.settings.now()
        today = moment.date()
        last_day = today + dt.timedelta(days=days - 1)

        lessons = [
            lesson
            for lesson in snapshot.lessons
            if today <= lesson.date <= last_day and _matches_subgroup(lesson, subgroup)
        ]

        day_objects = [
            DayOut(d=date.isoformat(), l=[self._to_wire(x) for x in items])
            for date, items in _group_by_date(lessons)
        ]

        # The hash covers the final days array only, so different ?subgroup= and
        # ?days= get different ETags without any extra bookkeeping.
        content_hash = payload_hash([day.model_dump() for day in day_objects])

        return ScheduleOut(
            gid=group_id,
            g=snapshot.group_name,
            gen=moment.isoformat(timespec="seconds"),
            src=snapshot.fetched_at.isoformat(timespec="seconds"),
            stale=self.is_stale(snapshot, moment),
            h=content_hash,
            days=day_objects,
        )

    def _to_wire(self, lesson: Lesson) -> LessonOut:
        return LessonOut(
            p=lesson.pair,
            n=self.abbreviate(lesson.subject),
            t=self.abbreviate.lesson_type(lesson.type),
            r=lesson.room,
            tc=lesson.teacher,
            sg=lesson.subgroup,
        )

    # ----------------------------------------------------------------- health

    def health(self, now: dt.datetime | None = None) -> dict[str, Any]:
        moment = now or self.settings.now()
        groups: dict[str, Any] = {}
        ok = True

        for group_id in self.settings.groups:
            state = self.store.state(group_id)
            snapshot = self.store.get(group_id)
            stale = snapshot is None or self.is_stale(snapshot, moment)
            if stale:
                ok = False
            groups[str(group_id)] = {
                "has_snapshot": snapshot is not None,
                "group_name": snapshot.group_name if snapshot else None,
                "last_success_at": _iso(state.last_success_at),
                "last_attempt_at": _iso(state.last_attempt_at),
                "last_error": state.last_error,
                "consecutive_failures": state.consecutive_failures,
                "lessons": len(snapshot.lessons) if snapshot else 0,
                "stale": stale,
            }

        return {
            "status": "ok" if ok else "degraded",
            "now": moment.isoformat(timespec="seconds"),
            "tz": self.settings.tz,
            "groups": groups,
        }


def _matches_subgroup(lesson: Lesson, subgroup: int | None) -> bool:
    """No filter keeps everything; a filter keeps common lessons plus your own."""
    if subgroup is None:
        return True
    return lesson.subgroup is None or lesson.subgroup == subgroup


def _group_by_date(lessons: list[Lesson]) -> list[tuple[dt.date, list[Lesson]]]:
    """Group into days, dropping empty ones. Input is already sorted."""
    grouped: dict[dt.date, list[Lesson]] = {}
    for lesson in lessons:
        grouped.setdefault(lesson.date, []).append(lesson)
    return [(date, grouped[date]) for date in sorted(grouped)]


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
