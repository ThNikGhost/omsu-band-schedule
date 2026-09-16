"""Content hash and ETag handling.

The hash covers the final `days` array only — after subgroup filtering, window
trimming and abbreviation. That gives different ETags for different ?subgroup=
and ?days= for free. `gen`/`src`/`stale` are deliberately excluded: including
them would change the ETag every 3 hours and push identical data over BLE.

Canonicalisation follows reference/studyhelper/hash_utils.py, except that the
`lesson_date` field is NOT dropped — here the dates are the point.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

HASH_LENGTH = 12


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, Cyrillic left unescaped."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def payload_hash(days: list[dict[str, Any]]) -> str:
    """First 12 hex chars of the SHA-256 of the canonical `days` JSON."""
    return hashlib.sha256(canonical_json(days).encode("utf-8")).hexdigest()[:HASH_LENGTH]


def make_etag(content_hash: str) -> str:
    return f'"{content_hash}"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """RFC 9110 If-None-Match check: comma separated list, W/ prefixes, or `*`."""
    if not if_none_match:
        return False
    header = if_none_match.strip()
    if header == "*":
        return True
    target = _strip_weak(etag)
    return any(_strip_weak(candidate.strip()) == target for candidate in header.split(","))


def _strip_weak(value: str) -> str:
    if value.startswith("W/"):
        value = value[2:]
    return value.strip()
