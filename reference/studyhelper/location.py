"""Location formatting utility."""

from __future__ import annotations

import re

_KORPUS_RE = re.compile(r"(?:корпус|корп\.?)\s*", re.IGNORECASE)


def _clean_building(building: str | None) -> str | None:
    """Extract building number from various formats.

    Handles: "Корпус 1", "1 корпус", "корпус 1", "(4)", "4".

    Args:
        building: Raw building string.

    Returns:
        Cleaned building number or None.
    """
    if not building:
        return None
    b = building.strip()
    b = b.replace("(", "").replace(")", "")
    b = _KORPUS_RE.sub("", b).strip()
    return b or None


def _clean_room(room: str | None) -> str | None:
    """Extract room number, handling "зал" and "ауд." variants.

    Handles: "113", "113) Спортивный зал", "Спортивный зал", "ауд. 114 Спортивный зал".

    Args:
        room: Raw room string.

    Returns:
        Cleaned room number or None.
    """
    if not room:
        return None
    r = room.strip()
    r = r.replace("(", "").replace(")", "")
    r = re.sub(r"ауд(?:итория)?\.?\s*", "", r, flags=re.IGNORECASE).strip()
    if re.search(r"зал", r, re.IGNORECASE):
        m = re.match(r"^(\d+)", r)
        return m.group(1) if m else None
    return r.strip() or None


def format_location(building: str | None, room: str | None) -> str | None:
    """Build compact location string like '4-101'.

    Normalizes building and room from various formats to a compact
    "{building}-{room}" representation.

    Args:
        building: Building name (e.g. "Корпус 1", "1 корпус", "4").
        room: Room number (e.g. "101", "113) Спортивный зал").

    Returns:
        Compact location string or None if both are absent.
    """
    b = _clean_building(building)
    r = _clean_room(room)
    if b and r:
        return f"{b}-{r}"
    return r or b or None
