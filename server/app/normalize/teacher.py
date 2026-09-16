"""Full name -> "Фамилия И. О.".

The API gives 66 distinct teacher values for group 5028. All of them are exactly
three words except the literal "-" (189 lessons), which means "no teacher".
One value has a dash for the patronymic: "Ямпольский Алексей -".
"""

from __future__ import annotations

import re

# Values that mean "unknown", written various ways over the years.
_EMPTY = {"", "-", "--", "—", "–", "не указан", "не указано", "нет", "n/a"}

_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

MAX_INITIALS = 2


def format_teacher(raw: str | None) -> str | None:
    """Compact teacher label, or None when the API has no real name."""
    if raw is None:
        return None

    name = " ".join(raw.split())
    if name.casefold() in _EMPTY:
        return None

    parts = [part for part in name.split(" ") if part.casefold() not in _EMPTY]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]

    surname, rest = _split_surname(parts)

    # Split on dots first, so "Д.Э." yields two initials while "Данил" yields one.
    initials: list[str] = []
    for token in rest:
        for piece in token.split("."):
            letters = _LETTER.findall(piece)
            if not letters:
                continue
            initials.append(f"{letters[0].upper()}.")
            if len(initials) >= MAX_INITIALS:
                break
        if len(initials) >= MAX_INITIALS:
            break

    if not initials:
        return surname
    return f"{surname} {' '.join(initials)}"


def _split_surname(parts: list[str]) -> tuple[str, list[str]]:
    """Handle both "Иванов И. И." and the rarer "И. И. Иванов" ordering."""
    first = parts[0]
    looks_like_initial = first.endswith(".") or len(first.rstrip(".")) == 1
    if looks_like_initial:
        return parts[-1], parts[:-1]
    return first, parts[1:]
