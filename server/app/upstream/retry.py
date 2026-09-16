"""Retry with exponential backoff, without external dependencies like tenacity.

Ported from reference/studyhelper/retry.py. Changes from the original:
  * jitter, so repeated failures from several groups do not line up;
  * httpx.RequestError covers the whole transport family instead of listing four
    subclasses (httpx.PoolTimeout and friends were previously not retried).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

# Every transport-level failure (timeout, connect, read, write, pool) is transient.
RETRYABLE_EXCEPTIONS = (httpx.RequestError,)

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behaviour."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: float = 0.25,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


DEFAULT_RETRY_CONFIG = RetryConfig()


def calculate_delay(
    attempt: int, config: RetryConfig, *, rand: Callable[[], float] | None = None
) -> float:
    """Delay before retry number ``attempt`` (0-indexed), capped and jittered."""
    delay = config.base_delay * (config.exponential_base**attempt)
    delay = min(delay, config.max_delay)
    if config.jitter:
        roll = rand() if rand is not None else random.random()  # noqa: S311 - backoff jitter, not crypto
        delay *= 1.0 + config.jitter * (2.0 * roll - 1.0)
    return max(0.0, delay)


def is_retryable_exception(exc: BaseException) -> bool:
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> Any:
    """Call an async function, retrying transient failures.

    A returned httpx.Response with a retryable status is retried too; on the last
    attempt raise_for_status() turns it into an exception for the caller.
    """
    config = config or DEFAULT_RETRY_CONFIG

    for attempt in range(config.max_attempts):
        is_last = attempt >= config.max_attempts - 1
        try:
            result = await func(*args, **kwargs)

            if isinstance(result, httpx.Response) and is_retryable_status(result.status_code):
                if is_last:
                    result.raise_for_status()
                    return result
                delay = calculate_delay(attempt, config)
                logger.warning(
                    "retryable status %d, attempt %d/%d, waiting %.1fs",
                    result.status_code,
                    attempt + 1,
                    config.max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            return result

        except httpx.HTTPStatusError as exc:
            if not is_retryable_status(exc.response.status_code) or is_last:
                raise
            delay = calculate_delay(attempt, config)
            logger.warning(
                "retryable HTTP %d, attempt %d/%d, waiting %.1fs",
                exc.response.status_code,
                attempt + 1,
                config.max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

        except Exception as exc:
            if not is_retryable_exception(exc) or is_last:
                raise
            delay = calculate_delay(attempt, config)
            logger.warning(
                "retryable error %s: %s, attempt %d/%d, waiting %.1fs",
                type(exc).__name__,
                exc,
                attempt + 1,
                config.max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("retry loop exhausted without returning or raising")
