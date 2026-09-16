"""normalize_response: the quirks of the real feed."""

from __future__ import annotations

import datetime as dt

import pytest

from app.errors import DataExtractionError
from app.models import Snapshot
from app.normalize.lesson import normalize_response, parse_api_date, parse_subgroup

WINDOW = (dt.date(2026, 9, 1), dt.date(2026, 10, 31))
FETCHED = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=6)))


def build(days, **kwargs) -> Snapshot:
    return normalize_response(
        {"success": True, "data": days},
        group_id=kwargs.pop("group_id", 5028),
        window=kwargs.pop("window", WINDOW),
        fetched_at=kwargs.pop("fetched_at", FETCHED),
    )


def lesson(**overrides):
    base = {
        "day": "16.09.2026",
        "time": 1,
        "lesson": "Теория информации Лек",
        "type_work": "Лек",
        "teacher": "Бесценный Игорь Павлович",
        "auditCorps": "4-303",
        "group": "МБС-301-О-01",
        "week": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("МБС-301-О-01/1", 1),
        ("МБС-301-О-01/2", 2),
        ("МБС-301-О-01", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_subgroup(value: str | None, expected: int | None) -> None:
    assert parse_subgroup(value) == expected


def test_parse_api_date() -> None:
    assert parse_api_date("16.09.2026") == dt.date(2026, 9, 16)
    assert parse_api_date("nonsense") is None
    assert parse_api_date(None) is None


def test_missing_subgroup_key_gives_none() -> None:
    """The key is absent, not null, when there is no subgroup."""
    snapshot = build([{"day": "16.09.2026", "lessons": [lesson()]}])
    assert "subgroupName" not in lesson()
    assert snapshot.lessons[0].subgroup is None


def test_subgroup_parsed_from_slash_suffix() -> None:
    snapshot = build([{"day": "16.09.2026", "lessons": [lesson(subgroupName="МБС-301-О-01/2")]}])
    assert snapshot.lessons[0].subgroup == 2


def test_days_are_sorted_even_when_the_api_is_not() -> None:
    snapshot = build(
        [
            {"day": "18.09.2026", "lessons": [lesson(day="18.09.2026", time=2)]},
            {"day": "16.09.2026", "lessons": [lesson()]},
        ]
    )
    assert [x.date for x in snapshot.lessons] == [dt.date(2026, 9, 16), dt.date(2026, 9, 18)]


def test_identical_lessons_are_deduplicated() -> None:
    snapshot = build(
        [
            {"day": "16.09.2026", "lessons": [lesson(), lesson()]},
            {"day": "16.09.2026", "lessons": [lesson()]},
        ]
    )
    assert len(snapshot.lessons) == 1


def test_window_drops_past_and_far_future() -> None:
    snapshot = build(
        [
            {"day": "01.03.2024", "lessons": [lesson(day="01.03.2024")]},
            {"day": "16.09.2026", "lessons": [lesson()]},
            {"day": "01.03.2027", "lessons": [lesson(day="01.03.2027")]},
        ]
    )
    assert [x.date for x in snapshot.lessons] == [dt.date(2026, 9, 16)]


def test_invalid_date_is_skipped_and_counted() -> None:
    snapshot = build([{"day": "not-a-date", "lessons": [lesson(day="not-a-date")]}])
    assert snapshot.lessons == []
    assert snapshot.skipped == 1


@pytest.mark.parametrize("pair", [0, 9, 99, "x", None])
def test_pair_out_of_range_is_skipped(pair) -> None:
    snapshot = build([{"day": "16.09.2026", "lessons": [lesson(time=pair)]}])
    assert snapshot.lessons == []
    assert snapshot.skipped == 1


def test_group_name_comes_from_the_whole_dataset() -> None:
    """A group with no upcoming lessons still needs a name in the response."""
    snapshot = build([{"day": "01.03.2024", "lessons": [lesson(day="01.03.2024")]}])
    assert snapshot.lessons == []
    assert snapshot.group_name == "МБС-301-О-01"


def test_dash_teacher_becomes_null() -> None:
    snapshot = build([{"day": "16.09.2026", "lessons": [lesson(teacher="-")]}])
    assert snapshot.lessons[0].teacher is None
    assert snapshot.lessons[0].teacher_full is None


def test_unknown_room_becomes_null_but_raw_is_kept() -> None:
    snapshot = build([{"day": "16.09.2026", "lessons": [lesson(auditCorps="4-0")]}])
    assert snapshot.lessons[0].room is None
    assert snapshot.lessons[0].audit_raw == "4-0"


def test_success_false_raises() -> None:
    with pytest.raises(DataExtractionError):
        normalize_response(
            {"success": False, "message": "boom", "data": []},
            group_id=5028,
            window=WINDOW,
            fetched_at=FETCHED,
        )


def test_empty_data_raises() -> None:
    """An empty payload must never overwrite a good snapshot."""
    with pytest.raises(DataExtractionError):
        normalize_response(
            {"success": True, "data": []}, group_id=5028, window=WINDOW, fetched_at=FETCHED
        )


def test_non_object_payload_raises() -> None:
    with pytest.raises(DataExtractionError):
        normalize_response([], group_id=5028, window=WINDOW, fetched_at=FETCHED)


def test_empty_window_is_accepted(snapshot) -> None:
    """Data exists upstream but nothing falls inside the window: not an error.

    This is the normal state once the university stops publishing further ahead.
    """
    result = normalize_response(
        {"success": True, "data": [{"day": "01.03.2024", "lessons": [lesson(day="01.03.2024")]}]},
        group_id=5028,
        window=(dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
        fetched_at=FETCHED,
    )
    assert result.lessons == []
    assert result.upstream_lessons == 1


def test_real_fixture(snapshot) -> None:
    """The captured response normalises without losing anything unexpectedly."""
    assert snapshot.group_name == "МБС-301-О-01"
    assert snapshot.skipped == 0
    assert snapshot.lessons
    assert all(1 <= x.pair <= 8 for x in snapshot.lessons)
    # Sorted by (date, pair).
    keys = [(x.date, x.pair) for x in snapshot.lessons]
    assert keys == sorted(keys)
    # Subgroup lessons really do appear in this group.
    assert any(x.subgroup in (1, 2) for x in snapshot.lessons)
    # And the type_work values the reference mapper did not know about.
    assert {"ИПракт", "ПРК_Р"} & {x.type for x in snapshot.lessons}
