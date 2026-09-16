"""GET /api/v1/calendar/{group}.ics — subscribe-able feed for phone calendars.

The token has to live in the query string here: calendar clients subscribe by
URL and cannot send an Authorization header. app/logging.py redacts it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import Settings, get_settings
from app.deps import get_service, require_token
from app.errors import NoSnapshotError, UnknownGroupError
from app.ics import build_ics
from app.service import ScheduleService

router = APIRouter()


@router.get("/api/v1/calendar/{group}.ics")
async def get_calendar(
    group: int,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ScheduleService, Depends(get_service)],
    _token: Annotated[str, Depends(require_token)],
    subgroup: Annotated[int | None, Query(ge=1, le=9)] = None,
) -> Response:
    try:
        snapshot = service.require_snapshot(group)
    except UnknownGroupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except NoSnapshotError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            str(exc),
            headers={"Retry-After": "60"},
        ) from exc

    body = build_ics(
        snapshot,
        service.bells,
        tz=settings.tzinfo,
        subgroup=subgroup,
        now=settings.now(),
    )
    filename = f"{group}.ics" if subgroup is None else f"{group}-{subgroup}.ics"
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-cache, max-age=0",
        },
    )
