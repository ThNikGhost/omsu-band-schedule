"""Tests for schedule parser module."""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.parser.data_mapper import DataMapper
from src.parser.exceptions import MappingError
from src.parser.hash_utils import compute_schedule_hash
from src.schemas.schedule import DayOfWeek, LessonType, WeekType


class TestHashUtils:
    """Tests for hash_utils module."""

    def test_empty_entries_hash(self):
        """Empty entries should produce consistent hash."""
        hash1 = compute_schedule_hash([])
        hash2 = compute_schedule_hash([])
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64 hex characters

    def test_same_data_same_hash(self):
        """Same data should produce same hash."""
        entries = [
            {"day_of_week": 1, "start_time": "08:00", "subject_name": "Math"},
            {"day_of_week": 2, "start_time": "10:00", "subject_name": "Physics"},
        ]
        hash1 = compute_schedule_hash(entries)
        hash2 = compute_schedule_hash(entries)
        assert hash1 == hash2

    def test_different_order_same_hash(self):
        """Entries in different order should produce same hash (sorted internally)."""
        entries1 = [
            {"day_of_week": 2, "start_time": "10:00", "subject_name": "Physics"},
            {"day_of_week": 1, "start_time": "08:00", "subject_name": "Math"},
        ]
        entries2 = [
            {"day_of_week": 1, "start_time": "08:00", "subject_name": "Math"},
            {"day_of_week": 2, "start_time": "10:00", "subject_name": "Physics"},
        ]
        hash1 = compute_schedule_hash(entries1)
        hash2 = compute_schedule_hash(entries2)
        assert hash1 == hash2

    def test_different_data_different_hash(self):
        """Different data should produce different hash."""
        entries1 = [{"day_of_week": 1, "subject_name": "Math"}]
        entries2 = [{"day_of_week": 1, "subject_name": "Physics"}]
        hash1 = compute_schedule_hash(entries1)
        hash2 = compute_schedule_hash(entries2)
        assert hash1 != hash2

    def test_different_lesson_date_same_hash(self):
        """Entries differing only by lesson_date should produce the same hash.

        The lesson_date field changes weekly when the API returns a new week's
        schedule, but the actual schedule structure hasn't changed.
        """
        entries_week1 = [
            {
                "day_of_week": 1,
                "start_time": "08:00",
                "end_time": "09:30",
                "subject_name": "Math",
                "teacher_name": "Ivanov",
                "room": "301",
                "lesson_date": "2026-02-16",
            },
            {
                "day_of_week": 3,
                "start_time": "10:00",
                "end_time": "11:30",
                "subject_name": "Physics",
                "teacher_name": "Petrov",
                "room": "205",
                "lesson_date": "2026-02-18",
            },
        ]
        entries_week2 = [
            {
                "day_of_week": 1,
                "start_time": "08:00",
                "end_time": "09:30",
                "subject_name": "Math",
                "teacher_name": "Ivanov",
                "room": "301",
                "lesson_date": "2026-02-23",
            },
            {
                "day_of_week": 3,
                "start_time": "10:00",
                "end_time": "11:30",
                "subject_name": "Physics",
                "teacher_name": "Petrov",
                "room": "205",
                "lesson_date": "2026-02-25",
            },
        ]
        hash1 = compute_schedule_hash(entries_week1)
        hash2 = compute_schedule_hash(entries_week2)
        assert hash1 == hash2


class TestDataMapperTime:
    """Tests for DataMapper.parse_time."""

    def test_parse_time_hhmm(self):
        """Parse time in HH:MM format."""
        result = DataMapper.parse_time("08:30")
        assert result == time(8, 30)

    def test_parse_time_hmm(self):
        """Parse time in H:MM format."""
        result = DataMapper.parse_time("9:00")
        assert result == time(9, 0)

    def test_parse_time_with_dot(self):
        """Parse time with dot separator."""
        result = DataMapper.parse_time("14.45")
        assert result == time(14, 45)

    def test_parse_time_with_spaces(self):
        """Parse time with leading/trailing spaces."""
        result = DataMapper.parse_time("  10:15  ")
        assert result == time(10, 15)

    def test_parse_time_empty_raises(self):
        """Empty time string should raise MappingError."""
        with pytest.raises(MappingError, match="Empty time"):
            DataMapper.parse_time("")

    def test_parse_time_invalid_format_raises(self):
        """Invalid time format should raise MappingError."""
        with pytest.raises(MappingError, match="Invalid time format"):
            DataMapper.parse_time("abc")

    def test_parse_time_invalid_values_raises(self):
        """Invalid time values should raise MappingError."""
        with pytest.raises(MappingError, match="Invalid time values"):
            DataMapper.parse_time("25:00")


class TestDataMapperDayOfWeek:
    """Tests for DataMapper.parse_day_of_week."""

    @pytest.mark.parametrize(
        "day_str,expected",
        [
            ("понедельник", DayOfWeek.MONDAY),
            ("Понедельник", DayOfWeek.MONDAY),
            ("ПОНЕДЕЛЬНИК", DayOfWeek.MONDAY),
            ("вторник", DayOfWeek.TUESDAY),
            ("среда", DayOfWeek.WEDNESDAY),
            ("четверг", DayOfWeek.THURSDAY),
            ("пятница", DayOfWeek.FRIDAY),
            ("суббота", DayOfWeek.SATURDAY),
            ("воскресенье", DayOfWeek.SUNDAY),
        ],
    )
    def test_parse_day_full_name(self, day_str: str, expected: DayOfWeek):
        """Parse full day names in Russian."""
        result = DataMapper.parse_day_of_week(day_str)
        assert result == expected

    @pytest.mark.parametrize(
        "day_str,expected",
        [
            ("пн", DayOfWeek.MONDAY),
            ("вт", DayOfWeek.TUESDAY),
            ("ср", DayOfWeek.WEDNESDAY),
            ("чт", DayOfWeek.THURSDAY),
            ("пт", DayOfWeek.FRIDAY),
            ("сб", DayOfWeek.SATURDAY),
            ("вс", DayOfWeek.SUNDAY),
        ],
    )
    def test_parse_day_abbreviated(self, day_str: str, expected: DayOfWeek):
        """Parse abbreviated day names."""
        result = DataMapper.parse_day_of_week(day_str)
        assert result == expected

    def test_parse_day_empty_raises(self):
        """Empty day string should raise MappingError."""
        with pytest.raises(MappingError, match="Empty day"):
            DataMapper.parse_day_of_week("")

    def test_parse_day_unknown_raises(self):
        """Unknown day should raise MappingError."""
        with pytest.raises(MappingError, match="Unknown day"):
            DataMapper.parse_day_of_week("monday")


class TestDataMapperLessonType:
    """Tests for DataMapper.parse_lesson_type."""

    @pytest.mark.parametrize(
        "type_str,expected",
        [
            ("лекция", LessonType.LECTURE),
            ("Лекция", LessonType.LECTURE),
            ("лек", LessonType.LECTURE),
            ("лек.", LessonType.LECTURE),
            ("практика", LessonType.PRACTICE),
            ("практическое занятие", LessonType.PRACTICE),
            ("пр", LessonType.PRACTICE),
            ("пр.", LessonType.PRACTICE),
            ("лабораторная", LessonType.LAB),
            ("лабораторная работа", LessonType.LAB),
            ("лаб", LessonType.LAB),
            ("лаб.", LessonType.LAB),
            ("семинар", LessonType.SEMINAR),
            ("сем", LessonType.SEMINAR),
            ("экзамен", LessonType.EXAM),
            ("консультация", LessonType.CONSULTATION),
        ],
    )
    def test_parse_lesson_type(self, type_str: str, expected: LessonType):
        """Parse various lesson type strings."""
        result = DataMapper.parse_lesson_type(type_str)
        assert result == expected

    def test_parse_lesson_type_empty_returns_other(self):
        """Empty string should return OTHER."""
        result = DataMapper.parse_lesson_type("")
        assert result == LessonType.OTHER

    def test_parse_lesson_type_unknown_returns_other(self):
        """Unknown type should return OTHER."""
        result = DataMapper.parse_lesson_type("something unknown")
        assert result == LessonType.OTHER


class TestDataMapperWeekType:
    """Tests for DataMapper.parse_week_type."""

    @pytest.mark.parametrize(
        "week_str,expected",
        [
            ("нечетная", WeekType.ODD),
            ("нечётная", WeekType.ODD),
            ("нечет", WeekType.ODD),
            ("I", WeekType.ODD),
            ("1", WeekType.ODD),
            ("четная", WeekType.EVEN),
            ("чётная", WeekType.EVEN),
            ("чет", WeekType.EVEN),
            ("II", WeekType.EVEN),
            ("2", WeekType.EVEN),
        ],
    )
    def test_parse_week_type(self, week_str: str, expected: WeekType):
        """Parse various week type strings."""
        result = DataMapper.parse_week_type(week_str)
        assert result == expected

    def test_parse_week_type_none_returns_none(self):
        """None input should return None."""
        result = DataMapper.parse_week_type(None)
        assert result is None

    def test_parse_week_type_empty_returns_none(self):
        """Empty string should return None."""
        result = DataMapper.parse_week_type("")
        assert result is None


class TestDataMapperRoomAndBuilding:
    """Tests for DataMapper.parse_room_and_building."""

    def test_parse_format_dash(self):
        """Parse '2-215' format."""
        room, building = DataMapper.parse_room_and_building("2-215")
        assert room == "215"
        assert building == "2"

    def test_parse_format_dash_with_letter(self):
        """Parse '1-101а' format."""
        room, building = DataMapper.parse_room_and_building("1-101а")
        assert room == "101а"
        assert building == "1"

    def test_parse_format_text(self):
        """Parse 'корп. 2, ауд. 215' format."""
        room, building = DataMapper.parse_room_and_building("корп. 2, ауд. 215")
        assert room == "215"
        assert building == "2"

    def test_parse_plain_room(self):
        """Parse plain room number."""
        room, building = DataMapper.parse_room_and_building("315")
        assert room == "315"
        assert building is None

    def test_parse_empty_returns_none(self):
        """Empty input should return (None, None)."""
        room, building = DataMapper.parse_room_and_building("")
        assert room is None
        assert building is None


class TestParseAuditCorps:
    """Tests for OmsuScheduleParser._parse_audit_corps."""

    @staticmethod
    def _parse(audit_corps: str) -> tuple[str | None, str | None]:
        from src.parser import OmsuScheduleParser

        return OmsuScheduleParser._parse_audit_corps(audit_corps)

    def test_standard_format(self):
        """Parse '4-101' format."""
        building, room = self._parse("4-101")
        assert building == "4"
        assert room == "101"

    def test_with_parentheses(self):
        """Parse '(6-113) Спортивный зал'."""
        building, room = self._parse("(6-113) Спортивный зал")
        assert building == "6"
        assert room == "113"

    def test_parentheses_no_zal(self):
        """Parse '(4-320)'."""
        building, room = self._parse("(4-320)")
        assert building == "4"
        assert room == "320"

    def test_room_only(self):
        """Parse room-only string."""
        building, room = self._parse("315")
        assert building is None
        assert room == "315"

    def test_zal_without_number(self):
        """Parse '(5-Спортивный зал)' — room stays as-is when no number."""
        building, room = self._parse("(5-Спортивный зал)")
        assert building == "5"
        assert room == "Спортивный зал"

    def test_empty_string(self):
        """Empty input returns (None, None)."""
        building, room = self._parse("")
        assert building is None
        assert room is None

    def test_aud_prefix_with_building(self):
        """Parse 'ауд. 114) Спортивный зал, 6(' → building=6, room=114."""
        building, room = self._parse("ауд. 114) Спортивный зал, 6(")
        assert building == "6"
        assert room == "114"

    def test_aud_prefix_room_only(self):
        """Parse 'ауд. 301' → building=None, room=301."""
        building, room = self._parse("ауд. 301")
        assert building is None
        assert room == "301"

    def test_aud_prefix_no_comma(self):
        """Parse 'ауд. 114 Спортивный зал 6' without comma → building=None."""
        building, room = self._parse("ауд. 114 Спортивный зал 6")
        assert building is None
        assert room == "114"

    def test_aud_prefix_with_dash(self):
        """Parse 'ауд. 4-101' → building=4, room=101 (ауд. stripped before dash-split)."""
        building, room = self._parse("ауд. 4-101")
        assert building == "4"
        assert room == "101"


class TestDataMapperSubgroup:
    """Tests for DataMapper.parse_subgroup."""

    def test_parse_subgroup_number(self):
        """Parse plain number."""
        result = DataMapper.parse_subgroup("1")
        assert result == 1

    def test_parse_subgroup_with_text(self):
        """Parse '1 подгруппа'."""
        result = DataMapper.parse_subgroup("1 подгруппа")
        assert result == 1

    def test_parse_subgroup_none_returns_none(self):
        """None input should return None."""
        result = DataMapper.parse_subgroup(None)
        assert result is None

    def test_parse_subgroup_no_number_returns_none(self):
        """Input without number should return None."""
        result = DataMapper.parse_subgroup("подгруппа")
        assert result is None


class TestDataMapperSubgroupFromGroupName:
    """Tests for DataMapper.parse_subgroup_from_group_name."""

    def test_parse_subgroup_from_group_name_with_slash_1(self):
        """Extract subgroup 1 from 'МБС-301-О-01/1'."""
        result = DataMapper.parse_subgroup_from_group_name("МБС-301-О-01/1")
        assert result == 1

    def test_parse_subgroup_from_group_name_with_slash_2(self):
        """Extract subgroup 2 from 'МБС-301-О-01/2'."""
        result = DataMapper.parse_subgroup_from_group_name("МБС-301-О-01/2")
        assert result == 2

    def test_parse_subgroup_from_group_name_without_slash(self):
        """Group name without slash should return None."""
        result = DataMapper.parse_subgroup_from_group_name("МБС-301-О-01")
        assert result is None

    def test_parse_subgroup_from_group_name_empty(self):
        """Empty string should return None."""
        result = DataMapper.parse_subgroup_from_group_name("")
        assert result is None

    def test_parse_subgroup_from_group_name_none(self):
        """None input should return None."""
        result = DataMapper.parse_subgroup_from_group_name(None)
        assert result is None


class TestDataMapperMapRawEntry:
    """Tests for DataMapper.map_raw_entry."""

    def test_map_full_entry(self):
        """Map entry with all fields."""
        raw = {
            "day_of_week": "понедельник",
            "start_time": "08:00",
            "end_time": "09:30",
            "subject_name": "Математика",
            "lesson_type": "лекция",
            "teacher_name": "Иванов И.И.",
            "location": "2-215",
            "week_type": "нечетная",
            "subgroup": "1",
            "group_name": "ММБ-101",
            "notes": "Test note",
        }
        entry = DataMapper.map_raw_entry(raw)

        assert entry.day_of_week == DayOfWeek.MONDAY
        assert entry.start_time == time(8, 0)
        assert entry.end_time == time(9, 30)
        assert entry.subject_name == "Математика"
        assert entry.lesson_type == LessonType.LECTURE
        assert entry.teacher_name == "Иванов И.И."
        assert entry.room == "215"
        assert entry.building == "2"
        assert entry.week_type == WeekType.ODD
        assert entry.subgroup == 1
        assert entry.group_name == "ММБ-101"
        assert entry.notes == "Test note"

    def test_map_minimal_entry(self):
        """Map entry with only required fields."""
        raw = {
            "day_of_week": "вторник",
            "start_time": "10:00",
            "end_time": "11:30",
            "subject_name": "Физика",
        }
        entry = DataMapper.map_raw_entry(raw)

        assert entry.day_of_week == DayOfWeek.TUESDAY
        assert entry.subject_name == "Физика"
        assert entry.lesson_type == LessonType.OTHER
        assert entry.teacher_name is None

    def test_map_entry_with_int_day(self):
        """Map entry with day_of_week as integer."""
        raw = {
            "day_of_week": 3,
            "start_time": "12:00",
            "end_time": "13:30",
            "subject_name": "Химия",
        }
        entry = DataMapper.map_raw_entry(raw)
        assert entry.day_of_week == DayOfWeek.WEDNESDAY

    def test_map_entry_missing_subject_raises(self):
        """Missing subject_name should raise MappingError."""
        raw = {
            "day_of_week": "понедельник",
            "start_time": "08:00",
            "end_time": "09:30",
        }
        with pytest.raises(MappingError, match="subject_name"):
            DataMapper.map_raw_entry(raw)


class TestDataMapperMapApiEntry:
    """Tests for DataMapper.map_api_entry."""

    def test_map_api_entry_extracts_subgroup_from_subgroup_name(self):
        """map_api_entry should extract subgroup from subgroupName with slash."""
        raw = {
            "subject_name": "Физика",
            "day_of_week": 1,
            "start_time": "08:45",
            "end_time": "10:20",
            "lesson_type": "Лек",
            "teacher_name": "Иванов И.И.",
            "room": "215",
            "building": "2",
            "week_type": 0,
            "group_name": "МБС-301-О-01",
            "subgroupName": "МБС-301-О-01/1",
        }
        entry = DataMapper.map_api_entry(raw)

        assert entry.subgroup == 1
        assert entry.group_name == "МБС-301-О-01"

    def test_map_api_entry_subgroup_2(self):
        """map_api_entry should extract subgroup 2 from subgroupName."""
        raw = {
            "subject_name": "Математика",
            "day_of_week": 2,
            "start_time": "10:35",
            "end_time": "12:10",
            "lesson_type": "Пр",
            "group_name": "МБС-301-О-01",
            "subgroupName": "МБС-301-О-01/2",
        }
        entry = DataMapper.map_api_entry(raw)

        assert entry.subgroup == 2

    def test_map_api_entry_no_subgroup_when_no_subgroup_name(self):
        """map_api_entry should return None subgroup when subgroupName is not present."""
        raw = {
            "subject_name": "Философия",
            "day_of_week": 3,
            "start_time": "12:25",
            "end_time": "14:00",
            "group_name": "МБС-301-О-01",
        }
        entry = DataMapper.map_api_entry(raw)

        assert entry.subgroup is None


class TestOmsuScheduleParser:
    """Tests for OmsuScheduleParser class."""

    @pytest.mark.asyncio
    async def test_parser_context_manager(self):
        """Test parser as async context manager."""
        with patch("src.parser.omsu_parser.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            from src.parser import OmsuScheduleParser

            async with OmsuScheduleParser() as parser:
                assert parser._client is not None

            # Verify cleanup was called
            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_parser_without_context_manager(self):
        """Parser can work without context manager (creates temporary client)."""
        with patch("src.parser.omsu_parser.httpx.AsyncClient") as mock_client_class:
            # Create mock response
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "success": True,
                "data": [
                    {
                        "day": "10.02.2025",
                        "lessons": [
                            {
                                "lesson": "Test Subject Лек",
                                "type_work": "Лек",
                                "time": 1,
                                "teacher": "Test Teacher",
                                "auditCorps": "4-101",
                                "group": "TST-101",
                                "week": 0,
                            }
                        ],
                    }
                ],
            }
            mock_response.raise_for_status = MagicMock()

            # Create mock client
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            from src.parser import OmsuScheduleParser

            parser = OmsuScheduleParser()
            result = await parser.parse()

            assert result.entries_count == 1
            assert result.entries[0].subject_name == "Test Subject"
