"""canonical_json, payload_hash, etag_matches."""

from __future__ import annotations

import pytest

from app.hashing import HASH_LENGTH, canonical_json, etag_matches, make_etag, payload_hash

DAYS = [{"d": "2026-09-16", "l": [{"p": 1, "n": "Теория инф.", "t": "Лек", "r": "4-303"}]}]


def test_hash_is_twelve_lowercase_hex() -> None:
    value = payload_hash(DAYS)
    assert len(value) == HASH_LENGTH
    assert value == value.lower()
    assert all(c in "0123456789abcdef" for c in value)


def test_hash_is_stable() -> None:
    assert payload_hash(DAYS) == payload_hash(DAYS)


def test_hash_ignores_key_order() -> None:
    reordered = [{"l": DAYS[0]["l"], "d": DAYS[0]["d"]}]
    assert payload_hash(reordered) == payload_hash(DAYS)


def test_hash_changes_with_content() -> None:
    other = [{"d": "2026-09-17", "l": DAYS[0]["l"]}]
    assert payload_hash(other) != payload_hash(DAYS)


def test_empty_days_hash_is_stable() -> None:
    assert payload_hash([]) == payload_hash([])
    assert payload_hash([]) != payload_hash(DAYS)


def test_canonical_json_keeps_cyrillic_readable() -> None:
    """ensure_ascii=False keeps the hash input compact and greppable."""
    assert "Теория" in canonical_json(DAYS)
    assert "\\u" not in canonical_json(DAYS)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('"abc123abc123"', True),
        ('W/"abc123abc123"', True),
        ("*", True),
        ('"other", "abc123abc123"', True),
        ('"other"', False),
        ("", False),
        (None, False),
    ],
)
def test_etag_matches(header: str | None, expected: bool) -> None:
    assert etag_matches(header, make_etag("abc123abc123")) is expected
