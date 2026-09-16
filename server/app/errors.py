"""Domain exceptions.

Ported from reference/studyhelper/exceptions.py; ElementNotFoundError was dropped
(it was a leftover from a Playwright-based parser that no longer exists).
"""


class ParserError(Exception):
    """Base exception for upstream parsing errors."""


class UpstreamError(ParserError):
    """The university API could not be reached or returned a bad HTTP status."""


class DataExtractionError(ParserError):
    """The university API answered, but the payload is not usable."""


class MappingError(ParserError):
    """A single lesson could not be mapped to our model."""


class NoSnapshotError(Exception):
    """No successful fetch has happened yet for this group."""

    def __init__(self, group_id: int) -> None:
        super().__init__(f"no snapshot for group {group_id} yet")
        self.group_id = group_id


class UnknownGroupError(Exception):
    """The requested group is not in the configured GROUPS list."""

    def __init__(self, group_id: int) -> None:
        super().__init__(f"group {group_id} is not served by this instance")
        self.group_id = group_id
