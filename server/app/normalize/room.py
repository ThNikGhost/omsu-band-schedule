"""auditCorps -> a short room label like "4-101".

Written from scratch rather than reused from reference/studyhelper/omsu_parser.py:
that implementation splits on the first hyphen anywhere in the string, which
mangles the real value "(М-82) Спортивный зал пр. Мира, 82" into building
"(М" / room "82)". The reference test cases are kept as regression tests.

All 50 distinct auditCorps values seen in the 2023-2026 feed for group 5028 are
covered by tests (see tests/data/omsu_distinct_values.json).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

MAX_ROOM_LENGTH = 12

# Building may be a digit ("4-101") or a letter code ("М-82").
_BUILDING_ROOM = re.compile(r"^(?P<b>[0-9A-Za-zА-Яа-яЁё]{1,3})-(?P<r>[^,]+)")
_PARENTHESISED = re.compile(r"^\((?P<inner>[^)]+)\)")
_AUD_PREFIX = re.compile(r"^ауд(?:итория)?\.?\s*", re.IGNORECASE)
_LEADING_DIGITS = re.compile(r"^(\d+)")
_ROOM_TOKEN = re.compile(r"^(\d+\w*)")
# Legacy garbage from the API: "ауд. 114) Спортивный зал, 6(" -> building 6, room 114.
_TRAILING_BUILDING = re.compile(r",\s*(?:корп(?:ус)?\.?\s*)?(\d+)\s*$", re.IGNORECASE)
_HALL = re.compile(r"зал", re.IGNORECASE)

# Rooms that carry no number: show a short label instead of a wall of text.
ROOM_ALIASES = {
    "спортивный зал": "Спортзал",
    "тренажерный зал": "Тренажёрный",
    "тренажёрный зал": "Тренажёрный",
    "фитнесс зал": "Фитнес",
    "фитнес зал": "Фитнес",
    "актовый зал": "Актовый",
    "бассейн": "Бассейн",
    "дистант": "Дистант",
}

# "4-0" (233 occurrences) means the room is unknown. Showing "4-0" on a 212px
# screen is worse than showing nothing, so it becomes None.
_UNKNOWN_ROOMS = {"0", "00"}

# Sentinel for "this shape did not match at all", as opposed to a matched shape
# that resolves to None because the room is unknown.
_NO_MATCH = object()


def format_room(audit_corps: str | None) -> str | None:
    """Best-effort short room label, or None when there is nothing useful to show."""
    if not audit_corps:
        return None

    raw = " ".join(audit_corps.split())
    if not raw:
        return None

    if "дистан" in raw.casefold():
        return "Дистант"

    # "(6-115) Бассейн" / "(М-82) Спортивный зал пр. Мира, 82" -> take the bracket.
    inner = _PARENTHESISED.match(raw)
    if inner:
        parsed = _parse_building_room(inner.group("inner").strip())
        if parsed is not _NO_MATCH:
            return parsed  # type: ignore[return-value]

    cleaned = _AUD_PREFIX.sub("", raw.replace("(", " ").replace(")", " ")).strip()
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None

    parsed = _parse_building_room(cleaned)
    if parsed is not _NO_MATCH:
        return parsed  # type: ignore[return-value]

    # "ауд. 114 Спортивный зал, 6" -> room first, building after the comma.
    token = _ROOM_TOKEN.match(cleaned)
    if token:
        room = token.group(1)
        if room in _UNKNOWN_ROOMS:
            return None
        building = _TRAILING_BUILDING.search(cleaned)
        return f"{building.group(1)}-{room}" if building else room

    alias = ROOM_ALIASES.get(cleaned.casefold())
    if alias:
        return alias

    logger.debug("unrecognised auditCorps: %r", audit_corps)
    return cleaned[:MAX_ROOM_LENGTH].strip() or None


def _parse_building_room(text: str) -> object:
    """Parse "BUILDING-ROOM".

    Returns the label, None when the room is explicitly unknown ("4-0"), or the
    _NO_MATCH sentinel when the text is not of this shape at all.
    """
    match = _BUILDING_ROOM.match(text)
    if not match:
        return _NO_MATCH

    building = match.group("b").strip()
    room = _clean_room(match.group("r").strip())
    if room is None:
        return None
    return f"{building}-{room}"


def _clean_room(room: str) -> str | None:
    """Reduce the room part to something short, or None when it is unknown."""
    room = room.strip()
    if not room:
        return None

    # "113 Спортивный зал" -> "113"; "Спортивный зал" -> alias.
    if _HALL.search(room):
        digits = _LEADING_DIGITS.match(room)
        if digits:
            room = digits.group(1)
        else:
            return ROOM_ALIASES.get(room.casefold(), room)[:MAX_ROOM_LENGTH]

    if room in _UNKNOWN_ROOMS:
        return None

    return room[:MAX_ROOM_LENGTH]
