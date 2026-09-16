"""Internal models (full values, stored on disk) and wire models (short keys).

Names are abbreviated only when a response is built, never on the way to disk:
editing abbreviations.yaml then takes effect on restart without re-fetching 1.5 MB.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_SCHEMA_VERSION = 1
WIRE_VERSION = 1


class Lesson(BaseModel):
    """One lesson as stored in a snapshot."""

    model_config = ConfigDict(frozen=True)

    date: dt.date
    pair: int = Field(ge=1, le=8)
    subject: str
    type: str
    room: str | None = None
    audit_raw: str | None = None
    teacher: str | None = None
    teacher_full: str | None = None
    subgroup: int | None = None

    def sort_key(self) -> tuple:
        return (self.date, self.pair, self.subgroup or 0, self.subject, self.type)

    def dedup_key(self) -> tuple:
        return (self.date, self.pair, self.subject, self.type, self.subgroup, self.room)


class Snapshot(BaseModel):
    """Everything we know about one group after a successful fetch."""

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    group_id: int
    group_name: str | None = None
    fetched_at: dt.datetime
    window_start: dt.date
    window_end: dt.date
    upstream_days: int = 0
    upstream_lessons: int = 0
    skipped: int = 0
    lessons: list[Lesson] = Field(default_factory=list)


class GroupState(BaseModel):
    """Sync bookkeeping. Written on failures too, so /health can explain itself."""

    group_id: int
    last_attempt_at: dt.datetime | None = None
    last_success_at: dt.datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


class LessonOut(BaseModel):
    """Wire format. Short keys keep the BLE payload small."""

    model_config = ConfigDict(extra="forbid")

    p: int
    n: str
    t: str
    r: str | None = None
    tc: str | None = None
    sg: int | None = None


class DayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    d: str
    l: list[LessonOut]  # noqa: E741 - part of the wire contract


class ScheduleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: int = WIRE_VERSION
    gid: int
    g: str | None = None
    gen: str
    src: str
    stale: bool = False
    h: str
    days: list[DayOut]
