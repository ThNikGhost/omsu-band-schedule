"""GET /api/v1/schedule — the compact payload the watch eventually receives."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.config import Settings, get_settings
from app.deps import get_service, require_token
from app.errors import NoSnapshotError, UnknownGroupError
from app.hashing import etag_matches, make_etag
from app.models import ScheduleOut
from app.service import ScheduleService

router = APIRouter()


@router.get("/api/v1/schedule", response_model=ScheduleOut, response_model_exclude_none=False)
async def get_schedule(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ScheduleService, Depends(get_service)],
    _token: Annotated[str, Depends(require_token)],
    group: Annotated[int, Query(description="Group id, must be one of GROUPS")],
    days: Annotated[int, Query(ge=1, description="Days ahead, including today")] = 14,
    subgroup: Annotated[
        int | None,
        Query(ge=1, le=9, description="Keep common lessons plus this subgroup"),
    ] = None,
) -> Response:
    if days > settings.days_ahead_max:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"days must not exceed DAYS_AHEAD_MAX ({settings.days_ahead_max})",
        )

    try:
        payload = service.build_payload(group, days=days, subgroup=subgroup)
    except UnknownGroupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except NoSnapshotError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            str(exc),
            headers={"Retry-After": "60"},
        ) from exc

    etag = make_etag(payload.h)
    headers = {
        "ETag": etag,
        "Cache-Control": "no-cache, max-age=0",
        "X-Schedule-Stale": "1" if payload.stale else "0",
    }

    # Stale data always goes out in full: `stale` is not part of the hash, so a
    # 304 would leave the client believing its cache is still current.
    if not payload.stale and etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    response.headers.update(headers)
    return Response(
        content=payload.model_dump_json(),
        media_type="application/json",
        headers=headers,
    )
