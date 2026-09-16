"""Bell schedule: pair number -> wall clock times.

Times are minutes from midnight in shared/bells.json so the watch can compare
them to the current time without parsing anything.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class PairTimes:
    pair: int
    start: int
    end: int

    def start_time(self) -> dt.time:
        return dt.time(self.start // 60, self.start % 60)

    def end_time(self) -> dt.time:
        return dt.time(self.end // 60, self.end % 60)


class Bells:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self._pairs = {
            int(item["p"]): PairTimes(int(item["p"]), int(item["start"]), int(item["end"]))
            for item in raw["pairs"]
        }

    @classmethod
    def load(cls, path: Path) -> Bells:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        bells = cls(raw)
        bells.validate()
        return bells

    def validate(self) -> None:
        """Fail loudly at startup rather than serving nonsense times."""
        if not self._pairs:
            raise ValueError("bells.json has no pairs")
        previous_end = -1
        for pair in sorted(self._pairs):
            times = self._pairs[pair]
            if not 0 <= times.start < times.end <= MINUTES_PER_DAY:
                raise ValueError(f"pair {pair} has invalid bounds {times.start}..{times.end}")
            if times.start < previous_end:
                raise ValueError(f"pair {pair} starts before pair {pair - 1} ends")
            previous_end = times.end

        for item in self.raw["pairs"]:
            halves = item.get("halves") or []
            for half in halves:
                if not (item["start"] <= half["start"] < half["end"] <= item["end"]):
                    raise ValueError(f"pair {item['p']} has a half outside its own bounds")

    def get(self, pair: int) -> PairTimes | None:
        return self._pairs.get(pair)

    def span(
        self, pair: int, date: dt.date, tz: dt.tzinfo
    ) -> tuple[dt.datetime, dt.datetime] | None:
        """Absolute start/end of a pair on a given date, or None if unknown."""
        times = self.get(pair)
        if times is None:
            return None
        return (
            dt.datetime.combine(date, times.start_time(), tzinfo=tz),
            dt.datetime.combine(date, times.end_time(), tzinfo=tz),
        )
