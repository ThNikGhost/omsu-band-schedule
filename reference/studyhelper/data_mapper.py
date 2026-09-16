"""Data mapper for converting raw parsed data to schema objects."""

from __future__ import annotations

import re
from datetime import date, time
from typing import Any

from src.parser.exceptions import MappingError
from src.schemas.schedule import (
    DayOfWeek,
    LessonType,
    ScheduleEntryCreate,
    WeekType,
)

# Day of week mapping (Russian → ISO number)
DAY_OF_WEEK_MAP: dict[str, int] = {
    "понедельник": 1,
    "вторник": 2,
    "среда": 3,
    "четверг": 4,
    "пятница": 5,
    "суббота": 6,
    "воскресенье": 7,
    # Abbreviated forms
    "пн": 1,
    "вт": 2,
    "ср": 3,
    "чт": 4,
    "пт": 5,
    "сб": 6,
    "вс": 7,
}

# Lesson type mapping (Russian → LessonType)
LESSON_TYPE_MAP: dict[str, LessonType] = {
    # Full forms
    "лекция": LessonType.LECTURE,
    "лекции": LessonType.LECTURE,
    "практика": LessonType.PRACTICE,
    "практическое занятие": LessonType.PRACTICE,
    "практические занятия": LessonType.PRACTICE,
    "лабораторная": LessonType.LAB,
    "лабораторная работа": LessonType.LAB,
    "лабораторные работы": LessonType.LAB,
    "семинар": LessonType.SEMINAR,
    "экзамен": LessonType.EXAM,
    "консультация": LessonType.CONSULTATION,
    # Abbreviated forms
    "лек": LessonType.LECTURE,
    "лек.": LessonType.LECTURE,
    "пр": LessonType.PRACTICE,
    "пр.": LessonType.PRACTICE,
    "прак": LessonType.PRACTICE,
    "прак.": LessonType.PRACTICE,
    "практ": LessonType.PRACTICE,
    "практ.": LessonType.PRACTICE,
    "лаб": LessonType.LAB,
    "лаб.": LessonType.LAB,
    "сем": LessonType.SEMINAR,
    "сем.": LessonType.SEMINAR,
}

# Week type mapping
WEEK_TYPE_MAP: dict[str, WeekType] = {
    "нечетная": WeekType.ODD,
    "нечётная": WeekType.ODD,
    "нечет": WeekType.ODD,
    "нечет.": WeekType.ODD,
    "i": WeekType.ODD,
    "1": WeekType.ODD,
    "четная": WeekType.EVEN,
    "чётная": WeekType.EVEN,
    "чет": WeekType.EVEN,
    "чет.": WeekType.EVEN,
    "ii": WeekType.EVEN,
    "2": WeekType.EVEN,
}


class DataMapper:
    """Mapper for converting raw parsed data to schema objects."""

    @staticmethod
    def parse_time(time_str: str) -> time:
        """Parse time string to time object.

        Args:
            time_str: Time in format "HH:MM" or "HH.MM" or "H:MM".

        Returns:
            datetime.time object.

        Raises:
            MappingError: If time format is invalid.
        """
        if not time_str:
            raise MappingError("Empty time string")

        # Normalize separators
        normalized = time_str.strip().replace(".", ":")

        # Try parsing
        match = re.match(r"^(\d{1,2}):(\d{2})$", normalized)
        if not match:
            raise MappingError(f"Invalid time format: {time_str}")

        hours, minutes = int(match.group(1)), int(match.group(2))

        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise MappingError(f"Invalid time values: {time_str}")

        return time(hour=hours, minute=minutes)

    @staticmethod
    def parse_day_of_week(day_str: str | int) -> DayOfWeek:
        """Parse day of week string or int to DayOfWeek enum.

        Args:
            day_str: Day name in Russian (full or abbreviated) or integer (1-7).

        Returns:
            DayOfWeek enum value.

        Raises:
            MappingError: If day name is not recognized.
        """
        # Handle integer input
        if isinstance(day_str, int):
            if 1 <= day_str <= 7:
                return DayOfWeek(day_str)
            raise MappingError(f"Invalid day number: {day_str}")

        if not day_str:
            raise MappingError("Empty day string")

        normalized = day_str.strip().lower()
        day_num = DAY_OF_WEEK_MAP.get(normalized)

        if day_num is None:
            raise MappingError(f"Unknown day of week: {day_str}")

        return DayOfWeek(day_num)

    @staticmethod
    def parse_lesson_type(type_str: str) -> LessonType:
        """Parse lesson type string to LessonType enum.

        Args:
            type_str: Lesson type in Russian.

        Returns:
            LessonType enum value.

        Raises:
            MappingError: If lesson type is not recognized.
        """
        if not type_str:
            return LessonType.OTHER

        normalized = type_str.strip().lower()
        lesson_type = LESSON_TYPE_MAP.get(normalized)

        if lesson_type is None:
            # Try partial matching for unknown types
            for key, value in LESSON_TYPE_MAP.items():
                if key in normalized or normalized in key:
                    return value
            return LessonType.OTHER

        return lesson_type

    @staticmethod
    def parse_week_type(week_str: str | None) -> WeekType | None:
        """Parse week type string to WeekType enum.

        Args:
            week_str: Week type string or None.

        Returns:
            WeekType enum value or None for both weeks.
        """
        if not week_str:
            return None

        normalized = week_str.strip().lower()
        return WEEK_TYPE_MAP.get(normalized)

    @staticmethod
    def parse_room_and_building(location: str) -> tuple[str | None, str | None]:
        """Parse location string into room and building.

        Args:
            location: Location string like "ауд. 215, корп. 2" or "2-215".

        Returns:
            Tuple of (room, building) or (None, None).
        """
        if not location:
            return None, None

        room = None
        building = None

        # Pattern: "2-215" or "1-101а"
        match = re.match(r"^(\d+)-(\d+\w*)$", location.strip())
        if match:
            building = match.group(1)
            room = match.group(2)
            return room, building

        # Pattern: "корп. 2, ауд. 215" or similar
        building_match = re.search(r"корп(?:ус)?\.?\s*(\d+)", location, re.IGNORECASE)
        room_match = re.search(r"ауд(?:итория)?\.?\s*(\d+\w*)", location, re.IGNORECASE)

        if building_match:
            building = building_match.group(1)
        if room_match:
            room = room_match.group(1)

        # If no patterns matched, treat whole string as room
        if room is None and building is None:
            room = location.strip()

        return room, building

    @staticmethod
    def parse_subgroup(subgroup_str: str | None) -> int | None:
        """Parse subgroup string to integer.

        Args:
            subgroup_str: Subgroup string like "1 подгруппа" or "1".

        Returns:
            Subgroup number or None.
        """
        if not subgroup_str:
            return None

        # Extract first number
        match = re.search(r"(\d+)", subgroup_str)
        if match:
            return int(match.group(1))

        return None

    @staticmethod
    def parse_subgroup_from_group_name(group_name: str | None) -> int | None:
        """Extract subgroup number from group name with slash notation.

        Args:
            group_name: Group name like "МБС-301-О-01/1" or "МБС-301-О-01".

        Returns:
            Subgroup number (1, 2, etc.) or None if no subgroup specified.

        Examples:
            "МБС-301-О-01/1" → 1
            "МБС-301-О-01/2" → 2
            "МБС-301-О-01" → None
            "" → None
            None → None
        """
        if not group_name:
            return None

        match = re.search(r"/(\d+)$", group_name)
        return int(match.group(1)) if match else None

    @classmethod
    def map_api_entry(cls, raw: dict[str, Any]) -> ScheduleEntryCreate:
        """Map API response entry to ScheduleEntryCreate schema.

        Args:
            raw: Entry dictionary from OmGU API with keys:
                - subject_name: Subject name
                - start_time: Start time string (HH:MM)
                - end_time: End time string (HH:MM)
                - day_of_week: Day of week (1-7)
                - lesson_type: Lesson type string ("Лек", "Пр", etc.)
                - teacher_name: Teacher full name
                - room: Room number
                - building: Building number
                - week_type: Week type (0, 1, 2)
                - group_name: Group name
                - subgroupName: Subgroup name with slash notation (e.g. "МБС-301-О-01/1")

        Returns:
            ScheduleEntryCreate schema object.

        Raises:
            MappingError: If required fields are missing or invalid.
        """
        if "subject_name" not in raw or not raw["subject_name"]:
            raise MappingError("Missing required field: subject_name")

        # Day of week is already an int from parser
        day_of_week = cls.parse_day_of_week(raw.get("day_of_week", 1))

        # Time is already in HH:MM format
        start_time = cls.parse_time(raw.get("start_time", "08:45"))
        end_time = cls.parse_time(raw.get("end_time", "10:20"))

        # Lesson type
        lesson_type = cls.parse_lesson_type(raw.get("lesson_type", ""))

        # Week type from API (0 = both, 1 = odd, 2 = even, or similar)
        week_type = cls._parse_api_week_type(raw.get("week_type"))

        # Lesson date from parser
        lesson_date_value: date | None = raw.get("lesson_date")

        return ScheduleEntryCreate(
            lesson_date=lesson_date_value,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            week_type=week_type,
            subject_name=raw["subject_name"].strip(),
            lesson_type=lesson_type,
            teacher_name=raw.get("teacher_name", "").strip() or None,
            room=raw.get("room"),
            building=raw.get("building"),
            group_name=raw.get("group_name", "").strip() or None,
            subgroup=cls.parse_subgroup_from_group_name(raw.get("subgroupName")),
            notes=None,
        )

    @staticmethod
    def _parse_api_week_type(week_value: int | None) -> WeekType | None:
        """Parse week type from API integer value.

        Args:
            week_value: 0 = both weeks, 1 = odd, 2 = even (assumption).

        Returns:
            WeekType enum value or None for both weeks.
        """
        if week_value is None or week_value == 0:
            return None
        if week_value == 1:
            return WeekType.ODD
        if week_value == 2:
            return WeekType.EVEN
        return None

    @classmethod
    def map_raw_entry(cls, raw: dict[str, Any]) -> ScheduleEntryCreate:
        """Map raw parsed entry to ScheduleEntryCreate schema.

        Args:
            raw: Raw entry dictionary with keys:
                - day_of_week: Day name in Russian
                - start_time: Start time string
                - end_time: End time string
                - subject_name: Subject name
                - lesson_type: Lesson type string
                - teacher_name: Teacher name (optional)
                - location: Location string (optional)
                - week_type: Week type string (optional)
                - subgroup: Subgroup string (optional)
                - group_name: Group name (optional)
                - notes: Notes (optional)

        Returns:
            ScheduleEntryCreate schema object.

        Raises:
            MappingError: If required fields are missing or invalid.
        """
        # Required fields
        if "subject_name" not in raw or not raw["subject_name"]:
            raise MappingError("Missing required field: subject_name")

        day_of_week = cls.parse_day_of_week(raw.get("day_of_week", ""))

        start_time = cls.parse_time(raw.get("start_time", ""))
        end_time = cls.parse_time(raw.get("end_time", ""))
        lesson_type = cls.parse_lesson_type(raw.get("lesson_type", ""))
        week_type = cls.parse_week_type(raw.get("week_type"))

        # Location parsing
        room, building = cls.parse_room_and_building(raw.get("location", ""))

        # Override if explicit room/building provided
        if raw.get("room"):
            room = raw["room"]
        if raw.get("building"):
            building = raw["building"]

        return ScheduleEntryCreate(
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            week_type=week_type,
            subject_name=raw["subject_name"].strip(),
            lesson_type=lesson_type,
            teacher_name=raw.get("teacher_name", "").strip() or None,
            room=room,
            building=building,
            group_name=raw.get("group_name", "").strip() or None,
            subgroup=cls.parse_subgroup(raw.get("subgroup")),
            notes=raw.get("notes", "").strip() or None,
        )
