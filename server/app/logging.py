"""Logging setup with token redaction.

The .ics feed has to carry its token in the query string (calendar apps cannot
send headers), so any log line that echoes a URL is a token leak. Uvicorn access
logs are off; this filter covers everything else.
"""

from __future__ import annotations

import logging
import re

_TOKEN_IN_URL = re.compile(r"((?:token|api_token|access_token)=)[^&\s\"']+", re.IGNORECASE)
_BEARER = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)


def redact(text: str) -> str:
    text = _TOKEN_IN_URL.sub(r"\1***", text)
    return _BEARER.sub(r"\1***", text)


class RedactTokensFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(RedactTokensFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
