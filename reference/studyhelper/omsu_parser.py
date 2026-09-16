"""OmGU schedule parser using HTTP API."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from src.config import settings
from src.parser.data_mapper import DataMapper
from src.parser.exceptions import DataExtractionError, PageLoadError
from src.parser.hash_utils import compute_schedule_hash
from src.parser.retry import RetryConfig, retry_async
from src.schemas.schedule import ScheduleEntryCreate

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests (seconds)
DEFAULT_TIMEOUT = 30

# Time slots mapping (pair number -> start_time, end_time)
# Based on OmGU schedule format
TIME_SLOTS: dict[int, tuple[str, str]] = {
    1: ("08:45", "10:20"),
    2: ("10:30", "12:05"),
    3: ("12:45", "14:20"),
    4: ("14:30", "16:05"),
    5: ("16:15", "17:50"),
    6: ("18:00", "19:35"),
    7: ("19:45", "21:20"),
    8: ("21:30", "23:05"),
}


@dataclass
class ParseResult:
    """Result of schedule parsing."""

    entries: list[ScheduleEntryCreate] = field(default_factory=list)
    raw_data: list[dict[str, Any]] = field(default_factory=list)
    content_hash: str = ""
    source_url: str = ""
    parsed_date: date = field(default_factory=date.today)
    errors: list[str] = field(default_factory=list)

    @property
    def entries_count(self) -> int:
        """Get number of parsed entries."""
        return len(self.entries)

    @property
    def has_errors(self) -> bool:
        """Check if parsing had errors."""
        return len(self.errors) > 0


class OmsuScheduleParser:
    """HTTP-based parser for OmGU schedule API.

    Usage:
        async with OmsuScheduleParser() as parser:
            result = await parser.parse()
            for entry in result.entries:
                print(entry.subject_name)

    Or without context manager:
        parser = OmsuScheduleParser()
        result = await parser.parse()
    """

    # API URL template
    API_URL_TEMPLATE = (
        "https://eservice.omsu.ru/schedule/backend/schedule/group/{group_id}"
    )

    def __init__(
        self,
        url: str | None = None,
        group_id: int | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        headless: bool = True,  # Kept for backwards compatibility, ignored
    ) -> None:
        """Initialize parser.

        Args:
            url: Full API URL. Defaults to constructed from group_id.
            group_id: Group ID for schedule. Defaults to settings.schedule_group_id.
            timeout: HTTP request timeout in seconds.
            headless: Ignored, kept for backwards compatibility.
        """
        self.group_id = group_id or settings.schedule_group_id
        self.url = url or self.API_URL_TEMPLATE.format(group_id=self.group_id)
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OmsuScheduleParser:
        """Create HTTP client."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        logger.info("HTTP client created for schedule parsing")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("HTTP client closed")

    async def parse(self, url: str | None = None) -> ParseResult:
        """Parse schedule from API.

        Args:
            url: URL to parse. Defaults to instance URL.

        Returns:
            ParseResult with parsed entries and metadata.

        Raises:
            PageLoadError: If API request fails.
            DataExtractionError: If data extraction fails.
        """
        target_url = url or self.url
        logger.info("Parsing schedule from API: %s", target_url)

        result = ParseResult(
            source_url=target_url,
            parsed_date=datetime.now(ZoneInfo(settings.timezone)).date(),
        )

        try:
            # Fetch JSON from API
            json_data = await self._fetch_json(target_url)

            if not json_data.get("success"):
                raise DataExtractionError(
                    f"API returned error: {json_data.get('message', 'Unknown error')}"
                )

            # Extract and flatten lessons from all days
            raw_entries = self._extract_lessons(json_data.get("data", []))
            result.raw_data = raw_entries

            # Map to schema objects
            for raw in raw_entries:
                try:
                    entry = DataMapper.map_api_entry(raw)
                    result.entries.append(entry)
                except Exception as e:
                    error_msg = f"Failed to map entry: {e}"
                    logger.warning(error_msg)
                    result.errors.append(error_msg)

            # Compute hash
            result.content_hash = compute_schedule_hash(raw_entries)

            logger.info(
                "Parsed %d entries (hash: %s...)",
                len(result.entries),
                result.content_hash[:8],
            )

        except PageLoadError:
            raise
        except DataExtractionError:
            raise
        except Exception as e:
            raise DataExtractionError(f"Failed to extract schedule: {e}") from e

        return result

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        """Fetch JSON from API URL with retry logic.

        Uses exponential backoff for transient failures (timeout, 502, 503, 504).

        Args:
            url: API URL to fetch.

        Returns:
            Parsed JSON response.

        Raises:
            PageLoadError: If request fails after all retries.
        """
        # Use existing client or create temporary one
        client = self._client
        should_close = False

        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            should_close = True

        retry_config = RetryConfig(max_attempts=3, base_delay=1.0, max_delay=10.0)

        async def _do_fetch() -> dict[str, Any]:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

        try:
            return await retry_async(_do_fetch, config=retry_config)
        except httpx.HTTPStatusError as e:
            raise PageLoadError(
                f"API returned status {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise PageLoadError(f"Failed to fetch API: {e}") from e
        finally:
            if should_close:
                await client.aclose()

    def _extract_lessons(self, days_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract and normalize lessons from API response.

        Args:
            days_data: List of day objects from API.

        Returns:
            Flattened list of lesson dictionaries.
        """
        lessons = []

        for day_obj in days_data:
            day_str = day_obj.get("day", "")
            day_lessons = day_obj.get("lessons", [])

            # Parse the date for lesson_date field
            lesson_date = self._parse_date_string(day_str)

            for lesson in day_lessons:
                # Parse date to get day of week
                day_of_week = self._parse_date_to_weekday(day_str)

                # Get time from slot number
                time_slot = lesson.get("time", 1)
                start_time, end_time = TIME_SLOTS.get(time_slot, ("08:45", "10:20"))

                # Extract subject name and remove type suffix (Лек, Практ, Лаб, etc.)
                subject_name = self._clean_subject_name(
                    lesson.get("lesson", ""), lesson.get("type_work", "")
                )

                # Parse auditCorps (format: "building-room" like "4-101")
                audit_corps = lesson.get("auditCorps", "")
                building, room = self._parse_audit_corps(audit_corps)

                # Normalize to expected format
                normalized = {
                    "subject_name": subject_name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "day_of_week": day_of_week,
                    "lesson_type": lesson.get("type_work", ""),
                    "teacher_name": lesson.get("teacher", ""),
                    "room": room,
                    "building": building,
                    "lesson_date": lesson_date,
                    "group_name": lesson.get("group", ""),
                    "subgroupName": lesson.get("subgroupName", ""),
                }

                lessons.append(normalized)

        logger.debug("Extracted %d lessons from %d days", len(lessons), len(days_data))
        return lessons

    @staticmethod
    def _clean_subject_name(lesson_name: str, type_work: str) -> str:
        """Remove lesson type suffix from subject name.

        Args:
            lesson_name: Full lesson name like "Математика Лек".
            type_work: Lesson type like "Лек".

        Returns:
            Clean subject name without type suffix.
        """
        if not lesson_name:
            return ""

        subject_name = lesson_name.strip()

        # Remove type_work suffix if present
        if type_work and subject_name.endswith(f" {type_work}"):
            subject_name = subject_name[: -len(type_work) - 1].strip()

        return subject_name

    @staticmethod
    def _parse_date_string(date_str: str) -> date | None:
        """Parse date string to date object.

        Args:
            date_str: Date in format "DD.MM.YYYY".

        Returns:
            Date object or None if parsing fails.
        """
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
            return dt.date()
        except ValueError:
            logger.warning("Failed to parse date: %s", date_str)
            return None

    @staticmethod
    def _parse_date_to_weekday(date_str: str) -> int:
        """Parse date string to weekday number (1=Monday, 7=Sunday).

        Args:
            date_str: Date in format "DD.MM.YYYY".

        Returns:
            Weekday number (1-7).
        """
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
            # isoweekday: Monday=1, Sunday=7
            return dt.isoweekday()
        except ValueError:
            logger.warning("Failed to parse date: %s", date_str)
            return 1  # Default to Monday

    @staticmethod
    def _parse_audit_corps(audit_corps: str) -> tuple[str | None, str | None]:
        """Parse auditCorps string into building and room.

        Cleans parentheses, "ауд." prefix and extracts room numbers
        from "зал" variants.

        Examples:
            "4-101" → ("4", "101")
            "(6-113) Спортивный зал" → ("6", "113")
            "ауд. 114) Спортивный зал, 6(" → ("6", "114")

        Args:
            audit_corps: Raw auditCorps string from API.

        Returns:
            Tuple of (building, room).
        """
        if not audit_corps:
            return None, None

        # Strip parentheses: "(6-113) Спортивный зал" → "6-113 Спортивный зал"
        cleaned = audit_corps.replace("(", "").replace(")", "").strip()

        # Strip "ауд."/"аудитория" prefix before dash-split
        # so "ауд. 4-101" becomes "4-101" and splits correctly
        cleaned = re.sub(
            r"^ауд(?:итория)?\.?\s*", "", cleaned, flags=re.IGNORECASE
        ).strip()

        parts = cleaned.split("-", 1)
        if len(parts) == 2:
            building = parts[0].strip() or None
            room = parts[1].strip() or None
            # Room may contain "зал" suffix: "113 Спортивный зал" → "113"
            if room and re.search(r"зал", room, re.IGNORECASE):
                m = re.match(r"^(\d+)", room)
                room = m.group(1) if m else room
            return building, room

        # Try "ROOM ..., BUILDING" pattern
        # e.g. "114 Спортивный зал, 6" (after "ауд." was stripped above)
        num_match = re.match(r"(\d+\w*)", cleaned)
        if num_match:
            room = num_match.group(1)
            bld_match = re.search(
                r",\s*(?:корп(?:ус)?\.?\s*)?(\d+)\s*$", cleaned, re.IGNORECASE
            )
            building = bld_match.group(1) if bld_match else None
            return building, room

        # If no pattern matched, treat as room only
        return None, cleaned
