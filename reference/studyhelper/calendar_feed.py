"""Calendar feed service layer.

Handles token CRUD and ICS calendar generation.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event, vDuration, vText
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.models.calendar_feed import CalendarFeed
from src.models.schedule import ScheduleEntry
from src.models.semester import Semester
from src.models.user import User
from src.models.work import Work
from src.utils.location import format_location
from src.utils.schedule_filters import (
    filter_entries_by_user_prefs,
    resolve_hidden_subjects,
)

logger = logging.getLogger(__name__)

OMSK_TZ = ZoneInfo(settings.timezone)

LESSON_TYPE_NAMES = {
    "lecture": "Лекция",
    "practice": "Практика",
    "lab": "Лаб",
    "seminar": "Семинар",
    "exam": "Экзамен",
    "consultation": "Консультация",
    "other": "Другое",
}

WORK_TYPE_NAMES = {
    "homework": "ДЗ",
    "lab": "Лаб",
    "practice": "Практика",
    "course_work": "Курсовая",
    "report": "Реферат",
    "test": "Контрольная",
    "exam": "Экзамен",
    "other": "Другое",
}

TOKEN_LENGTH = 48  # secrets.token_urlsafe(48) → ~64 chars


# --- Token CRUD ---


async def get_feed_by_user(
    db: AsyncSession,
    user_id: int,
) -> CalendarFeed | None:
    """Get calendar feed for a user."""
    result = await db.execute(
        select(CalendarFeed).where(CalendarFeed.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_feed_by_token(
    db: AsyncSession,
    token: str,
) -> CalendarFeed | None:
    """Get calendar feed by public token."""
    result = await db.execute(select(CalendarFeed).where(CalendarFeed.token == token))
    return result.scalar_one_or_none()


async def create_or_regenerate_feed(
    db: AsyncSession,
    user_id: int,
) -> CalendarFeed:
    """Create a new calendar feed or regenerate token for existing one.

    Args:
        db: Database session.
        user_id: User ID.

    Returns:
        CalendarFeed with a fresh token.
    """
    feed = await get_feed_by_user(db, user_id)
    new_token = secrets.token_urlsafe(TOKEN_LENGTH)

    if feed is None:
        feed = CalendarFeed(user_id=user_id, token=new_token)
        db.add(feed)
    else:
        feed.token = new_token

    await db.flush()
    await db.commit()
    await db.refresh(feed)
    return feed


async def revoke_feed(
    db: AsyncSession,
    user_id: int,
) -> bool:
    """Revoke (delete) calendar feed for user.

    Returns:
        True if feed existed and was removed, False otherwise.
    """
    feed = await get_feed_by_user(db, user_id)
    if feed is None:
        return False
    await db.delete(feed)
    await db.commit()
    return True


async def update_last_accessed(
    db: AsyncSession,
    feed: CalendarFeed,
) -> None:
    """Update last_accessed_at timestamp (throttled to once per hour)."""
    now = datetime.now(UTC)
    if feed.last_accessed_at is not None and (now - feed.last_accessed_at) < timedelta(
        hours=1
    ):
        return
    feed.last_accessed_at = now
    await db.flush()
    await db.commit()


# --- ICS Generation ---


async def generate_ics(db: AsyncSession, user_id: int) -> bytes:
    """Generate an iCalendar (.ics) file for the user.

    Includes schedule entries and work deadlines for the current semester.

    Args:
        db: Database session.
        user_id: User ID.

    Returns:
        ICS file content as bytes.
    """
    # Load user for subgroup/PE filter
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return _empty_calendar(name="StudyHelper")

    # Find current semester
    result = await db.execute(
        select(Semester).where(Semester.is_current.is_(True)).limit(1)
    )
    semester = result.scalar_one_or_none()

    cal = Calendar()
    cal.add("prodid", "-//StudyHelper//studyhelper1.ru//RU")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"StudyHelper - {user.name}")
    cal.add("x-wr-timezone", settings.timezone)
    cal.add("refresh-interval", vDuration(timedelta(hours=6)))

    if semester is None or semester.start_date is None or semester.end_date is None:
        cal.add_missing_timezones()
        return cal.to_ical()

    # Load schedule entries for the semester
    entries = await _load_schedule_entries(db, semester.start_date, semester.end_date)

    # Filter by user preferences
    hidden_config = await resolve_hidden_subjects(db, user)
    filtered_entries = filter_entries_by_user_prefs(entries, user, hidden_config)

    # Add schedule events
    for entry in filtered_entries:
        event = _schedule_entry_to_event(entry)
        cal.add_component(event)

    # Load works with deadlines
    works = await _load_works_with_deadlines(db)
    for work in works:
        event = _work_to_event(work)
        cal.add_component(event)

    cal.add_missing_timezones()
    return cal.to_ical()


async def _load_schedule_entries(
    db: AsyncSession,
    start_date: datetime | object,
    end_date: datetime | object,
) -> list[ScheduleEntry]:
    """Load schedule entries for a date range."""
    result = await db.execute(
        select(ScheduleEntry)
        .where(
            ScheduleEntry.lesson_date >= start_date,
            ScheduleEntry.lesson_date <= end_date,
        )
        .order_by(ScheduleEntry.lesson_date, ScheduleEntry.start_time)
    )
    return list(result.scalars().all())


async def _load_works_with_deadlines(db: AsyncSession) -> list[Work]:
    """Load works that have deadlines, with subject eager-loaded."""
    result = await db.execute(
        select(Work)
        .where(Work.deadline.isnot(None))
        .options(selectinload(Work.subject))
        .order_by(Work.deadline)
    )
    return list(result.scalars().all())


def _schedule_entry_to_event(entry: ScheduleEntry) -> Event:
    """Convert a ScheduleEntry to an iCalendar VEVENT."""
    event = Event()

    lesson_type_name = LESSON_TYPE_NAMES.get(entry.lesson_type, entry.lesson_type)
    event.add("uid", f"schedule-{entry.id}@studyhelper1.ru")
    event.add("summary", f"{entry.subject_name} ({lesson_type_name})")

    if entry.lesson_date is not None:
        dtstart = datetime.combine(entry.lesson_date, entry.start_time, tzinfo=OMSK_TZ)
        dtend = datetime.combine(entry.lesson_date, entry.end_time, tzinfo=OMSK_TZ)
        event.add("dtstart", dtstart)
        event.add("dtend", dtend)

    # Location
    location = format_location(entry.building, entry.room)
    if location:
        event.add("location", location)

    # Description
    desc_parts = []
    if entry.teacher_name:
        desc_parts.append(f"Преподаватель: {entry.teacher_name}")
    if entry.subgroup:
        desc_parts.append(f"Подгруппа: {entry.subgroup}")
    if desc_parts:
        event.add("description", "\n".join(desc_parts))

    event.add("dtstamp", datetime.now(UTC))

    return event


def _work_to_event(work: Work) -> Event:
    """Convert a Work with deadline to an iCalendar VEVENT."""
    event = Event()

    work_type_name = WORK_TYPE_NAMES.get(work.work_type, work.work_type)
    event.add("uid", f"deadline-{work.id}@studyhelper1.ru")
    event.add("summary", f"[Дедлайн] {work.title} ({work_type_name})")

    if work.deadline is not None:
        if work.deadline_has_time:
            event.add("dtstart", work.deadline)
            event.add("dtend", work.deadline + timedelta(hours=1))
        else:
            # All-day event
            event.add("dtstart", work.deadline.date())
            event.add("dtend", work.deadline.date() + timedelta(days=1))

    # Description
    desc_parts = []
    if work.subject:
        desc_parts.append(f"Предмет: {work.subject.name}")
    if work.description:
        desc_parts.append(work.description)
    if desc_parts:
        event.add("description", "\n".join(desc_parts))

    event.add("dtstamp", datetime.now(UTC))

    # Alarms: 24h and 1h before
    alarm_24h = Alarm()
    alarm_24h.add("action", "DISPLAY")
    alarm_24h.add("description", vText(f"Дедлайн через 24 часа: {work.title}"))
    alarm_24h.add("trigger", vDuration(timedelta(hours=-24)))
    event.add_component(alarm_24h)

    alarm_1h = Alarm()
    alarm_1h.add("action", "DISPLAY")
    alarm_1h.add("description", vText(f"Дедлайн через 1 час: {work.title}"))
    alarm_1h.add("trigger", vDuration(timedelta(hours=-1)))
    event.add_component(alarm_1h)

    return event


def _empty_calendar(name: str = "StudyHelper") -> bytes:
    """Generate an empty calendar."""
    cal = Calendar()
    cal.add("prodid", "-//StudyHelper//studyhelper1.ru//RU")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", settings.timezone)
    cal.add("refresh-interval", vDuration(timedelta(hours=6)))
    cal.add_missing_timezones()
    return cal.to_ical()
