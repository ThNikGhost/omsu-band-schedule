"""Snapshot persistence.

JSON files rather than SQLite: there is exactly one writer (the scheduler), reads
are served from memory, a group holds dozens of lessons, and there are no queries
to speak of. A schema and migrations would buy nothing here, and a JSON file can
be read by eye on the server during debugging.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from app.models import SNAPSHOT_SCHEMA_VERSION, GroupState, Snapshot

logger = logging.getLogger(__name__)

STATE_FILE = "state.json"
SNAPSHOT_DIR = "snapshots"


class SnapshotStore:
    """In-memory snapshots, durably mirrored to disk."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.snapshot_dir = self.data_dir / SNAPSHOT_DIR
        self._snapshots: dict[int, Snapshot] = {}
        self._states: dict[int, GroupState] = {}

    def ensure_dirs(self) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- loading

    def load_all(self, group_ids: Sequence[int]) -> None:
        """Populate memory from disk. A corrupt file is a warning, not a crash."""
        self.ensure_dirs()
        for group_id in group_ids:
            snapshot = self._read_snapshot(group_id)
            if snapshot is not None:
                self._snapshots[group_id] = snapshot
        self._states = self._read_states(group_ids)

    def _read_snapshot(self, group_id: int) -> Snapshot | None:
        path = self.snapshot_dir / f"{group_id}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("snapshot %s is unreadable, ignoring: %s", path, exc)
            return None

        version = raw.get("schema_version")
        if version != SNAPSHOT_SCHEMA_VERSION:
            logger.warning("snapshot %s has schema_version %r, ignoring", path, version)
            return None

        try:
            return Snapshot.model_validate(raw)
        except ValueError as exc:
            logger.warning("snapshot %s does not validate, ignoring: %s", path, exc)
            return None

    def _read_states(self, group_ids: Sequence[int]) -> dict[int, GroupState]:
        path = self.data_dir / STATE_FILE
        states = {gid: GroupState(group_id=gid) for gid in group_ids}
        if not path.exists():
            return states
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("state file %s is unreadable, starting fresh: %s", path, exc)
            return states

        for key, value in (raw or {}).items():
            try:
                state = GroupState.model_validate(value)
            except ValueError as exc:
                logger.warning("state entry %r does not validate, ignoring: %s", key, exc)
                continue
            states[state.group_id] = state
        return states

    # ----------------------------------------------------------------- access

    def get(self, group_id: int) -> Snapshot | None:
        return self._snapshots.get(group_id)

    def state(self, group_id: int) -> GroupState:
        return self._states.setdefault(group_id, GroupState(group_id=group_id))

    def known_groups(self) -> list[int]:
        return sorted(self._snapshots)

    # ---------------------------------------------------------------- writing

    def put(self, snapshot: Snapshot) -> None:
        self._snapshots[snapshot.group_id] = snapshot
        self.ensure_dirs()
        path = self.snapshot_dir / f"{snapshot.group_id}.json"
        atomic_write(path, snapshot.model_dump_json().encode("utf-8"))

    def set_state(self, state: GroupState) -> None:
        self._states[state.group_id] = state
        self.ensure_dirs()
        payload = {
            str(gid): json.loads(item.model_dump_json())
            for gid, item in sorted(self._states.items())
        }
        atomic_write(
            self.data_dir / STATE_FILE,
            json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"),
        )


def atomic_write(path: Path, data: bytes) -> None:
    """Write via a sibling temp file and os.replace, then fsync the directory.

    The temp file must live in the same directory: os.replace is only atomic
    within one filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def _fsync_dir(directory: Path) -> None:
    """Best effort: Windows cannot open a directory for fsync."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
