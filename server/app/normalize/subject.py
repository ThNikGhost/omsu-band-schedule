"""Subject names: strip the lesson-type suffix, then shorten to fit the watch.

The screen is 212px wide, so the wire format caps names at 32 characters. Of the
51 distinct subjects in the 2023-2026 feed for group 5028, 18 exceed that, the
longest being 67 characters. Abbreviation rules live in abbreviations.yaml
(data, not code) and are applied when a response is built, so editing them takes
effect on restart without re-fetching the upstream feed.

Rule order: exact -> regex -> per-word -> drop parentheses -> truncate.
Truncation is a safety net for future subjects, not the main mechanism: the
shipped ruleset fits every known subject without it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAX_LEN = 32
DEFAULT_ELLIPSIS = "…"

# Suffixes the API appends to lesson names. Used when type_work is missing or
# does not match, e.g. "…практика ПРК_Р".
KNOWN_TYPE_SUFFIXES = ("ИПракт", "ПРК_Р", "Практ", "Прак", "Лек", "Лаб", "Сем", "Экз", "Конс")

# Never break a word if that would throw away more than this share of the budget.
_WORD_BREAK_FLOOR = 0.6

_PARENTHESISED = re.compile(r"\s*\([^)]*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")


def clean_subject_name(lesson: str | None, type_work: str | None) -> str:
    """Drop the trailing lesson-type marker: "Математика Лек" -> "Математика"."""
    if not lesson:
        return ""

    name = " ".join(lesson.split())

    if type_work:
        suffix = " " + " ".join(type_work.split())
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()

    for known in KNOWN_TYPE_SUFFIXES:
        if name.endswith(" " + known):
            return name[: -len(known) - 1].strip()

    return name


@dataclass
class AbbrevRules:
    max_len: int = DEFAULT_MAX_LEN
    ellipsis: str = DEFAULT_ELLIPSIS
    exact: dict[str, str] = field(default_factory=dict)
    regex: list[tuple[str, str]] = field(default_factory=list)
    words: dict[str, str] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    drop_parenthesised: bool = True


class Abbreviator:
    """Applies abbreviations.yaml to a cleaned subject name."""

    def __init__(self, rules: AbbrevRules) -> None:
        self.rules = rules
        self._exact = {_norm(k): v for k, v in rules.exact.items()}
        self._regex = [(re.compile(p, re.IGNORECASE), r) for p, r in rules.regex]
        # Longest first, so "информационных" wins over a shorter overlapping rule.
        self._words = [
            (re.compile(rf"(?<!\w){re.escape(key)}(?!\w)", re.IGNORECASE), _case_aware(value))
            for key, value in sorted(rules.words.items(), key=lambda kv: -len(kv[0]))
        ]

    @classmethod
    def from_yaml(cls, path: Path) -> Abbreviator:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        regex_rules = [(str(item[0]), str(item[1])) for item in data.get("regex") or []]
        rules = AbbrevRules(
            max_len=int(data.get("max_len", DEFAULT_MAX_LEN)),
            ellipsis=str(data.get("ellipsis", DEFAULT_ELLIPSIS)),
            exact={str(k): str(v) for k, v in (data.get("exact") or {}).items()},
            regex=regex_rules,
            words={
                str(k): "" if v is None else str(v) for k, v in (data.get("words") or {}).items()
            },
            types={str(k): str(v) for k, v in (data.get("types") or {}).items()},
            drop_parenthesised=bool(data.get("drop_parenthesised", True)),
        )
        return cls(rules)

    def lesson_type(self, type_work: str | None) -> str:
        """Map type_work through the optional `types` section."""
        if not type_work:
            return ""
        value = " ".join(type_work.split())
        return self.rules.types.get(value, value)

    def __call__(self, subject: str) -> str:
        if not subject:
            return ""

        text = _norm(subject)
        max_len = self.rules.max_len

        exact = self._exact.get(text)
        if exact is not None:
            return smart_truncate(exact, max_len, self.rules.ellipsis)

        for pattern, replacement in self._regex:
            if pattern.match(text):
                text = _norm(pattern.sub(replacement, text))
                break
        else:
            for pattern, replacement in self._words:
                text = pattern.sub(replacement, text)
            text = _tidy(text)

        if len(text) > max_len and self.rules.drop_parenthesised:
            candidate = _tidy(_PARENTHESISED.sub("", text))
            if candidate:
                text = candidate

        return smart_truncate(text, max_len, self.rules.ellipsis)


def smart_truncate(text: str, max_len: int, ellipsis: str = DEFAULT_ELLIPSIS) -> str:
    """Cut to max_len, preferring a word boundary and never returning empty."""
    if len(text) <= max_len:
        return text

    limit = max_len - len(ellipsis)
    if limit <= 0:
        return text[:max_len]

    cut = text[:limit]
    space = cut.rfind(" ")
    if space >= int(max_len * _WORD_BREAK_FLOOR):
        cut = cut[:space]

    cut = cut.rstrip(" ,.;:-")
    if not cut:
        cut = text[:limit]
    return cut + ellipsis


def _case_aware(replacement: str) -> Any:
    """Word rules match case-insensitively but keep the original leading case.

    So a single rule "информации: инф." abbreviates both "…информации" -> "…инф."
    and "Информации…" -> "Инф.…" without needing two dictionary entries.
    """

    def substitute(match: re.Match[str]) -> str:
        if not replacement:
            return ""
        head, tail = replacement[:1], replacement[1:]
        if match.group(0)[:1].isupper():
            return head.upper() + tail
        return head.lower() + tail

    return substitute


def _norm(text: str) -> str:
    return " ".join(text.split())


def _tidy(text: str) -> str:
    return _norm(_SPACE_BEFORE_PUNCT.sub(r"\1", text))
