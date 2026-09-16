"""Retry utilities for HTTP requests with exponential backoff.

Implements retry logic without external dependencies (like tenacity)
for handling transient network failures.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

# Exceptions that should trigger a retry
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
)

# HTTP status codes that should trigger a retry
RETRYABLE_STATUS_CODES = {502, 503, 504, 429}

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
    ) -> None:
        """Initialize retry configuration.

        Args:
            max_attempts: Maximum number of attempts (including initial).
            base_delay: Initial delay between retries in seconds.
            max_delay: Maximum delay between retries in seconds.
            exponential_base: Base for exponential backoff calculation.
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base


DEFAULT_RETRY_CONFIG = RetryConfig()


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for given attempt using exponential backoff.

    Args:
        attempt: Current attempt number (0-indexed).
        config: Retry configuration.

    Returns:
        Delay in seconds.
    """
    delay = config.base_delay * (config.exponential_base**attempt)
    return min(delay, config.max_delay)


def is_retryable_exception(exc: Exception) -> bool:
    """Check if exception should trigger a retry.

    Args:
        exc: Exception to check.

    Returns:
        True if exception is retryable.
    """
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def is_retryable_status(status_code: int) -> bool:
    """Check if HTTP status code should trigger a retry.

    Args:
        status_code: HTTP status code.

    Returns:
        True if status code is retryable.
    """
    return status_code in RETRYABLE_STATUS_CODES


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> Any:
    """Execute async function with retry logic.

    Args:
        func: Async function to execute.
        *args: Positional arguments for the function.
        config: Retry configuration. Uses defaults if not provided.
        **kwargs: Keyword arguments for the function.

    Returns:
        Result of the function.

    Raises:
        Exception: Last exception if all retries fail.
    """
    config = config or DEFAULT_RETRY_CONFIG
    last_exception: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            result = await func(*args, **kwargs)

            # Check for retryable HTTP response
            if isinstance(result, httpx.Response) and is_retryable_status(
                result.status_code
            ):
                if attempt < config.max_attempts - 1:
                    delay = calculate_delay(attempt, config)
                    logger.warning(
                        "Retryable status %d, attempt %d/%d, waiting %.1fs",
                        result.status_code,
                        attempt + 1,
                        config.max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    # Last attempt, raise to let caller handle
                    result.raise_for_status()

            return result

        except httpx.HTTPStatusError as exc:
            last_exception = exc

            if not is_retryable_status(exc.response.status_code):
                raise

            if attempt < config.max_attempts - 1:
                delay = calculate_delay(attempt, config)
                logger.warning(
                    "Retryable HTTP status %d, attempt %d/%d, waiting %.1fs",
                    exc.response.status_code,
                    attempt + 1,
                    config.max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d retry attempts failed with HTTP %d",
                    config.max_attempts,
                    exc.response.status_code,
                )
                raise

        except Exception as exc:
            last_exception = exc

            if not is_retryable_exception(exc):
                raise

            if attempt < config.max_attempts - 1:
                delay = calculate_delay(attempt, config)
                logger.warning(
                    "Retryable error: %s, attempt %d/%d, waiting %.1fs",
                    exc,
                    attempt + 1,
                    config.max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d retry attempts failed: %s",
                    config.max_attempts,
                    exc,
                )
                raise

    # Should not reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry logic error")


def with_retry(
    config: RetryConfig | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for adding retry logic to async functions.

    Args:
        config: Retry configuration.

    Returns:
        Decorator function.

    Example:
        @with_retry(RetryConfig(max_attempts=5))
        async def fetch_data(url: str) -> dict:
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(func, *args, config=config, **kwargs)

        return wrapper

    return decorator
