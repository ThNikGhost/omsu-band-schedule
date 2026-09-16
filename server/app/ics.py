"""ICS calendar feed.

Structure follows reference/studyhelper/calendar_feed.py (PRODID, REFRESH-INTERVAL,
add_missing_timezones, one VEVENT per lesson with no RRULE). The database and
per-user token machinery from that file is not carried over: this feed is per
group, and lesson times come from shared/bells.json rather than the API.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, vDuration

from app.bells import Bells
from app.models import Lesson, Snapshot

PRODID = "-//band-schedule//OmSU//RU"
REFRESH_INTERVAL = dt.timedelta(hours=6)

TYPE_LABELS = {
    "Лек": "Лекция",
    "Прак": "Практика",
    "Практ": "Практика",
    "ИПракт": "Практика (интеракт.)",
    "Лаб": "Лабораторная",
    "ПРК_Р": "Практика",
    "Сем": "Семинар",
    "Экз": "Экзамен",
}


def build_ics(
    snapshot: Snapshot,
    bells: Bells,
    *,
    tz: ZoneInfo,
    subgroup: int | None,
    now: dt.datetime,
) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", _calendar_name(snapshot, subgroup))
    calendar.add("x-wr-timezone", str(tz))
    calendar.add("refresh-interval", vDuration(REFRESH_INTERVAL))
    calendar.add("x-published-ttl", vDuration(REFRESH_INTERVAL))

    for lesson in snapshot.lessons:
        if subgroup is not None and lesson.subgroup not in (None, subgroup):
            continue
        event = _to_event(lesson, snapshot, bells, tz=tz, now=now)
        if event is not None:
            calendar.add_component(event)

    # Without this Apple Calendar and Google read Asia/Omsk times as UTC.
    calendar.add_missing_timezones()
    return calendar.to_ical()


def _calendar_name(snapshot: Snapshot, subgroup: int | None) -> str:
    name = snapshot.group_name or str(snapshot.group_id)
    return f"{name}/{subgroup}" if subgroup else name


def _to_event(
    lesson: Lesson,
    snapshot: Snapshot,
    bells: Bells,
    *,
    tz: ZoneInfo,
    now: dt.datetime,
) -> Event | None:
    span = bells.span(lesson.pair, lesson.date, tz)
    if span is None:
        return None
    start, end = span

    event = Event()
    # Derived from the slot, not from the API's lesson id: if a lesson is moved,
    # a stale id would leave a duplicate event behind in subscribed calendars.
    event.add(
        "uid",
        f"{snapshot.group_id}-{lesson.date:%Y%m%d}-{lesson.pair}-{lesson.subgroup or 0}@band.omsu",
    )
    event.add("summary", _summary(lesson))
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", now.astimezone(dt.UTC))

    if lesson.room:
        event.add("location", lesson.room)

    description = []
    if lesson.teacher_full:
        description.append(f"Преподаватель: {lesson.teacher_full}")
    if lesson.subgroup:
        description.append(f"Подгруппа: {lesson.subgroup}")
    if lesson.audit_raw and lesson.audit_raw != lesson.room:
        description.append(f"Аудитория: {lesson.audit_raw}")
    if description:
        event.add("description", "\n".join(description))

    return event


def _summary(lesson: Lesson) -> str:
    label = TYPE_LABELS.get(lesson.type, lesson.type)
    return f"{lesson.subject} ({label})" if label else lesson.subject
