"""Token checks and a small in-process rate limiter."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import deque
from collections.abc import Sequence


def check_token(candidate: str | None, valid: Sequence[str]) -> bool:
    """Constant-time-ish membership test.

    Every configured token is compared, with no early return, so the time taken
    does not reveal which token matched or how far down the list it is.
    """
    if not candidate or not valid:
        return False
    matched = False
    for token in valid:
        if secrets.compare_digest(candidate, token):
            matched = True
    return matched


def token_fingerprint(token: str) -> str:
    """Short hash used as a rate-limit key and in logs; never the token itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class RateLimiter:
    """Sliding window per key. Bounded, so a flood of keys cannot eat memory."""

    def __init__(self, limit: int, window_sec: float = 60.0, max_keys: int = 1024) -> None:
        self.limit = limit
        self.window = window_sec
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        """Record a request. Returns (allowed, retry_after_seconds)."""
        moment = time.monotonic() if now is None else now
        cutoff = moment - self.window

        bucket = self._hits.get(key)
        if bucket is None:
            if len(self._hits) >= self.max_keys:
                self._evict(cutoff)
            bucket = self._hits.setdefault(key, deque())

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.limit:
            retry_after = max(1, int(bucket[0] + self.window - moment) + 1)
            return False, retry_after

        bucket.append(moment)
        return True, 0

    def _evict(self, cutoff: float) -> None:
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self.max_keys:
            # Still full of active keys: drop the oldest to stay bounded.
            oldest = min(self._hits, key=lambda k: self._hits[k][-1])
            del self._hits[oldest]
