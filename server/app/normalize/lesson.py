"""Raw university payload -> a Snapshot.

Deliberately tolerant: one malformed lesson must not lose the whole day. Bad
records are counted in Snapshot.skipped instead of raising, which is the same
approach reference/studyhelper/omsu_parser.py takes.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from app.errors import DataExtractionError
from app.models import Lesson, Snapshot
from app.normalize.room import format_room
from app.normalize.subject import clean_subject_name
from app.normalize.teacher import format_teacher

logger = logging.getLogger(__name__)

MIN_PAIR = 1
MAX_PAIR = 8

_API_DATE = "%d.%m.%Y"
# "МБС-301-О-01/1" -> 1. From reference/studyhelper/data_mapper.py.
_SUBGROUP = re.compile(r"/(\d+)$")


def parse_subgroup(subgroup_name: str | None) -> int | None:
    """Subgroup number from the slash suffix, or None."""
    if not subgroup_name:
        return None
    match = _SUBGROUP.search(subgroup_name.strip())
    return int(match.group(1)) if match else None


def parse_api_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value.strip(), _API_DATE).date()  # noqa: DTZ007 - date only
    except ValueError:
        return None


def normalize_response(
    payload: Any,
    *,
    group_id: int,
    window: tuple[dt.date, dt.date],
    fetched_at: dt.datetime,
) -> Snapshot:
    """Validate the envelope, keep lessons inside `window`, sort and deduplicate."""
    if not isinstance(payload, dict):
        raise DataExtractionError("upstream response is not a JSON object")
    if not payload.get("success"):
        raise DataExtractionError(f"upstream reported failure: {payload.get('message', 'unknown')}")

    days = payload.get("data")
    if not isinstance(days, list) or not days:
        raise DataExtractionError("upstream returned no schedule data")

    start, end = window
    lessons: dict[tuple, Lesson] = {}
    skipped = 0
    upstream_lessons = 0
    group_name: str | None = None

    for day in days:
        if not isinstance(day, dict):
            skipped += 1
            continue

        day_lessons = day.get("lessons") or []
        upstream_lessons += len(day_lessons)

        date = parse_api_date(day.get("day"))
        for raw in day_lessons:
            if not isinstance(raw, dict):
                skipped += 1
                continue

            # The group name is taken from the whole dataset, not just the window:
            # a group with no upcoming lessons still needs a name in the response.
            if group_name is None:
                group_name = _group_name(raw)

            lesson_date = date or parse_api_date(raw.get("day"))
            if lesson_date is None:
                skipped += 1
                continue
            if not (start <= lesson_date <= end):
                continue

            lesson = _map_lesson(raw, lesson_date)
            if lesson is None:
                skipped += 1
                continue
            lessons.setdefault(lesson.dedup_key(), lesson)

    return Snapshot(
        group_id=group_id,
        group_name=group_name,
        fetched_at=fetched_at,
        window_start=start,
        window_end=end,
        upstream_days=len(days),
        upstream_lessons=upstream_lessons,
        skipped=skipped,
        lessons=sorted(lessons.values(), key=Lesson.sort_key),
    )


def _map_lesson(raw: dict[str, Any], date: dt.date) -> Lesson | None:
    try:
        pair = int(raw.get("time"))
    except (TypeError, ValueError):
        return None
    if not (MIN_PAIR <= pair <= MAX_PAIR):
        logger.debug("pair number out of range: %r", raw.get("time"))
        return None

    type_work = (raw.get("type_work") or "").strip()
    subject = clean_subject_name(raw.get("lesson"), type_work)
    if not subject:
        return None

    audit_raw = (raw.get("auditCorps") or "").strip() or None
    teacher_full = (raw.get("teacher") or "").strip() or None
    teacher = format_teacher(teacher_full)

    return Lesson(
        date=date,
        pair=pair,
        subject=subject,
        type=type_work,
        room=format_room(audit_raw),
        audit_raw=audit_raw,
        teacher=teacher,
        # Keep the full name only when it is a real one; "-" becomes None above.
        teacher_full=teacher_full if teacher else None,
        # The key is absent (not null) when there is no subgroup.
        subgroup=parse_subgroup(raw.get("subgroupName")),
    )


def _group_name(raw: dict[str, Any]) -> str | None:
    name = (raw.get("group") or "").strip()
    if not name:
        return None
    # Strip a "/1" suffix in case the plain group field ever carries one.
    return _SUBGROUP.sub("", name) or None
