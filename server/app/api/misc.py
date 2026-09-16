"""Bells, health and the admin refresh hook."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.deps import get_service, require_admin, require_token
from app.errors import UnknownGroupError
from app.service import ScheduleService

router = APIRouter()


@router.get("/api/v1/bells")
async def get_bells(
    service: Annotated[ScheduleService, Depends(get_service)],
    _token: Annotated[str, Depends(require_token)],
) -> dict[str, Any]:
    return service.bells.raw


@router.get("/health")
async def health(service: Annotated[ScheduleService, Depends(get_service)]) -> dict[str, Any]:
    """Unauthenticated, and always 200 while the process itself is healthy.

    A failing upstream must not restart the container: that would throw away the
    in-memory snapshots and rate-limit state for a problem on the university side.
    """
    return service.health()


@router.post("/api/v1/admin/refresh", dependencies=[Depends(require_admin)])
async def admin_refresh(
    service: Annotated[ScheduleService, Depends(get_service)],
    group: Annotated[int, Query()],
) -> dict[str, Any]:
    try:
        snapshot = await service.sync_group(group)
    except UnknownGroupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{type(exc).__name__}: {exc}",
        ) from exc

    return {
        "group": group,
        "fetched_at": snapshot.fetched_at.isoformat(timespec="seconds"),
        "lessons": len(snapshot.lessons),
        "skipped": snapshot.skipped,
    }
