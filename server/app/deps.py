"""FastAPI dependencies: settings, service, authentication, rate limiting."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status

from app.config import Settings, get_settings
from app.security import RateLimiter, check_token, token_fingerprint
from app.service import ScheduleService


def get_service(request: Request) -> ScheduleService:
    service: ScheduleService | None = getattr(request.app.state, "service", None)
    if service is None:  # pragma: no cover - only if startup failed
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "service not ready")
    return service


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter


def _extract_token(request: Request, query_token: str | None) -> str | None:
    """Bearer header first; ?token= exists because calendar apps cannot send headers."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return query_token


def require_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
    token: Annotated[
        str | None,
        Query(description="Fallback for clients that cannot send headers"),
    ] = None,
) -> str:
    candidate = _extract_token(request, token)
    if not check_token(candidate, settings.api_tokens):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    assert candidate is not None
    fingerprint = token_fingerprint(candidate)
    allowed, retry_after = limiter.hit(fingerprint)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    return fingerprint


def require_admin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Query()] = None,
) -> None:
    if not settings.admin_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "admin endpoint is disabled")
    candidate = _extract_token(request, token)
    if not check_token(candidate, [settings.admin_token]):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
