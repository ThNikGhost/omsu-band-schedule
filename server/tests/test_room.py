"""format_room.

The first block is ported verbatim from reference/studyhelper/test_parser.py
(TestParseAuditCorps), adjusted to our single-string output. Those inputs are
real garbage the university API has emitted, not invented edge cases.
"""

from __future__ import annotations

import pytest

from app.normalize.room import MAX_ROOM_LENGTH, format_room


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # --- ported from reference/studyhelper/test_parser.py -----------------
        ("4-101", "4-101"),
        ("(6-113) Спортивный зал", "6-113"),
        ("(4-320)", "4-320"),
        ("315", "315"),
        ("(5-Спортивный зал)", "5-Спортзал"),
        ("", None),
        ("ауд. 114) Спортивный зал, 6(", "6-114"),
        ("ауд. 301", "301"),
        ("ауд. 114 Спортивный зал 6", "114"),
        ("ауд. 4-101", "4-101"),
        # --- values the reference parser got wrong ---------------------------
        # split("-", 1) turned this into building "(М", room "82)".
        ("(М-82) Спортивный зал пр. Мира, 82", "М-82"),
        # --- our own rules ---------------------------------------------------
        ("4-0", None),
        ("4-00", None),
        ("Дистант", "Дистант"),
        ("дистанционно", "Дистант"),
        ("(6-115) Бассейн", "6-115"),
        ("(6-215) Тренажерный зал", "6-215"),
        ("7-419", "7-419"),
        (None, None),
        ("   ", None),
        ("Бассейн", "Бассейн"),
        ("Спортивный зал", "Спортзал"),
    ],
)
def test_format_room(value: str | None, expected: str | None) -> None:
    assert format_room(value) == expected


def test_unknown_room_is_none_not_building(sample: None = None) -> None:
    """Regression: "4-0" must not degrade to the building number alone."""
    assert format_room("4-0") is None
    assert format_room("4-0") != "4"


def test_all_real_values_are_short_and_safe(distinct) -> None:
    """Every auditCorps ever seen for group 5028 must map to something sane."""
    for value in distinct["audit_corps"]:
        result = format_room(value)
        assert result is None or (result and len(result) <= MAX_ROOM_LENGTH + 4), value


def test_every_numbered_room_keeps_its_building(distinct) -> None:
    """Values shaped like a real room must survive with building and number."""
    for value in distinct["audit_corps"]:
        result = format_room(value)
        if result is None or value == "Дистант":
            continue
        # Every remaining real value is either "B-N" or came out of a bracket.
        assert "-" in result, (value, result)
