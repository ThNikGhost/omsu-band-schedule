"""SnapshotStore and atomic_write."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.models import GroupState, Snapshot
from app.store import SnapshotStore, atomic_write


def test_roundtrip(settings, snapshot: Snapshot) -> None:
    store = SnapshotStore(settings.data_dir)
    store.put(snapshot)

    reloaded = SnapshotStore(settings.data_dir)
    reloaded.load_all([5028])
    restored = reloaded.get(5028)

    assert restored is not None
    assert restored.group_name == snapshot.group_name
    assert len(restored.lessons) == len(snapshot.lessons)
    assert restored.lessons[0] == snapshot.lessons[0]
    assert restored.fetched_at == snapshot.fetched_at


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "file.json"
    atomic_write(target, b"{}")
    assert target.read_bytes() == b"{}"
    assert list(tmp_path.rglob("*.tmp*")) == []


def test_atomic_write_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "file.json"
    atomic_write(target, b"old")
    atomic_write(target, b"new")
    assert target.read_bytes() == b"new"


def test_corrupt_snapshot_is_ignored(settings, snapshot: Snapshot) -> None:
    store = SnapshotStore(settings.data_dir)
    store.put(snapshot)
    (settings.data_dir / "snapshots" / "5028.json").write_text("{not json", encoding="utf-8")

    reloaded = SnapshotStore(settings.data_dir)
    reloaded.load_all([5028])
    assert reloaded.get(5028) is None


def test_unknown_schema_version_is_ignored(settings, snapshot: Snapshot) -> None:
    store = SnapshotStore(settings.data_dir)
    store.put(snapshot)
    path = settings.data_dir / "snapshots" / "5028.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"schema_version":1', '"schema_version":99'),
        encoding="utf-8",
    )

    reloaded = SnapshotStore(settings.data_dir)
    reloaded.load_all([5028])
    assert reloaded.get(5028) is None


def test_state_survives_restart(settings) -> None:
    store = SnapshotStore(settings.data_dir)
    moment = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=6)))
    store.set_state(
        GroupState(group_id=5028, last_attempt_at=moment, last_error="boom", consecutive_failures=2)
    )

    reloaded = SnapshotStore(settings.data_dir)
    reloaded.load_all([5028])
    state = reloaded.state(5028)
    assert state.consecutive_failures == 2
    assert state.last_error == "boom"
    assert state.last_success_at is None


def test_missing_data_dir_is_created(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "does" / "not" / "exist")
    store.load_all([5028])
    assert store.snapshot_dir.is_dir()
    assert store.get(5028) is None
