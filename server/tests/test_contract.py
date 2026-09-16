"""shared/schema.json, shared/bells.json and shared/example.json.

All three components are built against these files, so the contract is verified
here rather than described in prose.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.bells import Bells
from app.service import ScheduleService
from tests.conftest import NOW, SHARED

SCHEMA = json.loads((SHARED / "schema.json").read_text(encoding="utf-8"))
BELLS_RAW = json.loads((SHARED / "bells.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    Draft202012Validator.check_schema(SCHEMA)
    return Draft202012Validator(SCHEMA)


# ------------------------------------------------------------------- schema


def test_live_payload_validates(loaded_service: ScheduleService, validator) -> None:
    payload = loaded_service.build_payload(5028, days=14, subgroup=None, now=NOW)
    validator.validate(json.loads(payload.model_dump_json()))


def test_subgroup_payload_validates(loaded_service: ScheduleService, validator) -> None:
    payload = loaded_service.build_payload(5028, days=21, subgroup=2, now=NOW)
    validator.validate(json.loads(payload.model_dump_json()))


def test_empty_payload_validates(loaded_service: ScheduleService, validator) -> None:
    """days: [] is a normal state, not an error, once the feed runs out."""
    import datetime as dt

    payload = loaded_service.build_payload(
        5028, days=14, subgroup=None, now=NOW + dt.timedelta(days=400)
    )
    assert payload.days == []
    validator.validate(json.loads(payload.model_dump_json()))


def test_example_file_validates(validator) -> None:
    example = SHARED / "example.json"
    assert example.exists(), "run: uv run python -m app.cli gen-example --source <api dump>"
    validator.validate(json.loads(example.read_text(encoding="utf-8")))


def test_schema_rejects_unknown_fields(validator) -> None:
    bad = {
        "v": 1,
        "gid": 5028,
        "gen": "2026-09-16T12:00:00+06:00",
        "src": "2026-09-16T11:58:10+06:00",
        "stale": False,
        "h": "a1b2c3d4e5f6",
        "days": [],
        "surprise": 1,
    }
    assert not validator.is_valid(bad)


def test_schema_rejects_a_bad_hash(validator) -> None:
    bad = {
        "v": 1,
        "gid": 5028,
        "gen": "2026-09-16T12:00:00+06:00",
        "src": "2026-09-16T11:58:10+06:00",
        "stale": False,
        "h": "NOTAHASH",
        "days": [],
    }
    assert not validator.is_valid(bad)


# -------------------------------------------------------------------- bells


def test_bells_loads_and_validates() -> None:
    Bells.load(SHARED / "bells.json")


def test_bell_times_match_the_official_sheet() -> None:
    expected = {
        1: ("08:45", "09:30", "09:35", "10:20"),
        2: ("10:30", "11:15", "11:20", "12:05"),
        3: ("12:45", "13:30", "13:35", "14:20"),
        4: ("14:30", "15:15", "15:20", "16:05"),
        5: ("16:15", "17:00", "17:05", "17:50"),
        6: ("18:00", "18:45", "18:50", "19:35"),
    }
    for pair in BELLS_RAW["pairs"]:
        number = pair["p"]
        if number not in expected:
            continue
        halves = pair["halves"]
        assert (
            _hhmm(halves[0]["start"]),
            _hhmm(halves[0]["end"]),
            _hhmm(halves[1]["start"]),
            _hhmm(halves[1]["end"]),
        ) == expected[number]
        assert pair["start"] == halves[0]["start"]
        assert pair["end"] == halves[1]["end"]


def test_pairs_seven_and_eight_have_no_halves() -> None:
    """They are absent from the official sheet but do appear in the API."""
    for pair in BELLS_RAW["pairs"]:
        if pair["p"] in (7, 8):
            assert pair["halves"] == []


def test_big_break_sits_between_pairs_two_and_three() -> None:
    pairs = {p["p"]: p for p in BELLS_RAW["pairs"]}
    big = BELLS_RAW["big_break"]
    assert big["start"] == pairs[2]["end"]
    assert big["end"] == pairs[3]["start"]
    assert big["end"] - big["start"] == 40


def test_all_minutes_are_sane_integers() -> None:
    for pair in BELLS_RAW["pairs"]:
        for value in (pair["start"], pair["end"]):
            assert isinstance(value, int)
            assert 0 <= value < 24 * 60


def test_pairs_do_not_overlap() -> None:
    ordered = sorted(BELLS_RAW["pairs"], key=lambda p: p["p"])
    for previous, current in itertools.pairwise(ordered):
        assert previous["end"] <= current["start"], (previous["p"], current["p"])


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def test_bells_endpoint_file_is_the_shared_one(settings) -> None:
    assert Path(settings.bells_path).resolve() == (SHARED / "bells.json").resolve()
