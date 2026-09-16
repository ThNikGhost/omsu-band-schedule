"""clean_subject_name, Abbreviator and smart_truncate."""

from __future__ import annotations

import pytest

from app.normalize.subject import (
    Abbreviator,
    AbbrevRules,
    clean_subject_name,
    smart_truncate,
)


@pytest.mark.parametrize(
    ("lesson", "type_work", "expected"),
    [
        ("Технологии и методы программирования Лек", "Лек", "Технологии и методы программирования"),
        ("Математика Лек", "Лек", "Математика"),
        # type_work missing: fall back to the known suffix list.
        ("Учебная практика: проектная практика ПРК_Р", "", "Учебная практика: проектная практика"),
        ("Теория информации ИПракт", None, "Теория информации"),
        # No suffix at all.
        ("Физика", "Лек", "Физика"),
        ("", "Лек", ""),
        (None, "Лек", ""),
        # Whitespace is normalised.
        ("  Теория   информации  Лек ", "Лек", "Теория информации"),
    ],
)
def test_clean_subject_name(lesson: str | None, type_work: str | None, expected: str) -> None:
    assert clean_subject_name(lesson, type_work) == expected


def test_exact_rule_beats_word_rules(abbreviator: Abbreviator) -> None:
    assert abbreviator("Безопасность жизнедеятельности") == "БЖД"


def test_regex_rule_collapses_practice(abbreviator: Abbreviator) -> None:
    long = "Производственная практика: эксплуатационно-технологическая практика"
    assert abbreviator(long) == "Производств. практика"


def test_word_rule_mirrors_leading_case() -> None:
    rules = AbbrevRules(max_len=32, words={"информации": "инф."})
    abbreviate = Abbreviator(rules)
    assert abbreviate("Теория информации") == "Теория инф."
    assert abbreviate("Информации теория") == "Инф. теория"


def test_word_rule_with_empty_value_removes_word() -> None:
    rules = AbbrevRules(max_len=32, words={"элективная": ""})
    assert Abbreviator(rules)("Физкультура элективная дисциплина") == "Физкультура дисциплина"


def test_word_rules_do_not_match_inside_words() -> None:
    rules = AbbrevRules(max_len=64, words={"сети": "сет."})
    assert Abbreviator(rules)("Кассеты и сети") == "Кассеты и сет."


def test_parentheses_dropped_only_when_too_long() -> None:
    rules = AbbrevRules(max_len=20, drop_parenthesised=True)
    abbreviate = Abbreviator(rules)
    assert abbreviate("Курс (важный)") == "Курс (важный)"
    assert abbreviate("Очень длинный курс (важный)") == "Очень длинный курс"


@pytest.mark.parametrize(
    ("text", "max_len", "expected"),
    [
        ("короткая", 32, "короткая"),
        ("ровно тридцать два символа тут!!", 32, "ровно тридцать два символа тут!!"),
        # Breaks on a word boundary.
        ("Системы управления базами данных ещё", 32, "Системы управления базами…"),
        # A single long word has to be cut mid-word.
        ("Ааааааааааааааааааааааааааааааааааа", 10, "Ааааааааа…"),
    ],
)
def test_smart_truncate(text: str, max_len: int, expected: str) -> None:
    result = smart_truncate(text, max_len)
    assert result == expected
    assert len(result) <= max_len


def test_smart_truncate_never_returns_empty() -> None:
    assert smart_truncate("   слово", 4) != ""


def test_every_real_subject_fits_without_truncation(abbreviator: Abbreviator, distinct) -> None:
    """The shipped ruleset must cover every subject the feed has ever contained.

    A TRUNC here means abbreviations.yaml needs a rule, not that the test is wrong.
    """
    truncated = []
    for subject in distinct["subjects_stripped"]:
        result = abbreviator(subject)
        assert len(result) <= abbreviator.rules.max_len, (subject, result)
        assert result
        if result.endswith(abbreviator.rules.ellipsis):
            truncated.append((subject, result))
    assert truncated == []


def test_abbreviator_is_idempotent(abbreviator: Abbreviator, distinct) -> None:
    """Running twice must not keep shrinking the name."""
    for subject in distinct["subjects_stripped"]:
        once = abbreviator(subject)
        assert abbreviator(once) == once, subject


def test_lesson_type_mapping(abbreviator: Abbreviator) -> None:
    assert abbreviator.lesson_type("ИПракт") == "Практ"
    assert abbreviator.lesson_type("ПРК_Р") == "Практика"
    assert abbreviator.lesson_type("Лек") == "Лек"
    assert abbreviator.lesson_type("") == ""
    assert abbreviator.lesson_type(None) == ""
