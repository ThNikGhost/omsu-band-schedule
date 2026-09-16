"""format_teacher."""

from __future__ import annotations

import pytest

from app.normalize.teacher import format_teacher


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Вильховский Данил Эдуардович", "Вильховский Д. Э."),
        ("Гусс Святослав Владимирович", "Гусс С. В."),
        # Real value from the feed: the patronymic is a dash.
        ("Ямпольский Алексей -", "Ямпольский А."),
        ("-", None),
        ("", None),
        ("   ", None),
        (None, None),
        ("не указан", None),
        ("Иванов", "Иванов"),
        ("Иванов Иван", "Иванов И."),
        # Initials glued together.
        ("Вильховский Д.Э.", "Вильховский Д. Э."),
        # Initials first.
        ("Д. Э. Вильховский", "Вильховский Д. Э."),
        ("Петрова-Водкина Анна Ивановна", "Петрова-Водкина А. И."),
        ("  Гринь   Анатолий   Гаврилович  ", "Гринь А. Г."),
    ],
)
def test_format_teacher(value: str | None, expected: str | None) -> None:
    assert format_teacher(value) == expected


def test_all_real_teachers(distinct) -> None:
    """Every teacher value in the feed maps to None or "Surname I. O."."""
    for value in distinct["teachers"]:
        result = format_teacher(value)
        if value.strip() == "-":
            assert result is None
            continue
        assert result is not None
        assert len(result) <= 48
        # Surname plus at most two initials.
        assert len(result.split(" ")) <= 3
