"""Application wiring."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import calendar, misc, schedule
from app.bells import Bells
from app.config import Settings, get_settings
from app.logging import setup_logging
from app.normalize.subject import Abbreviator
from app.scheduler import SyncScheduler
from app.security import RateLimiter
from app.service import ScheduleService
from app.store import SnapshotStore
from app.upstream.omsu import OmsuClient, build_client

logger = logging.getLogger(__name__)


def build_service(settings: Settings) -> tuple[ScheduleService, object]:
    """Compose the service. Bad bells/abbreviations are fatal, by design."""
    bells = Bells.load(settings.bells_path)
    abbreviator = Abbreviator.from_yaml(settings.abbreviations_path)

    store = SnapshotStore(settings.data_dir)
    store.load_all(settings.groups)

    http = build_client(
        connect_timeout=settings.upstream_connect_timeout,
        read_timeout=settings.upstream_read_timeout,
    )
    client = OmsuClient(
        http,
        base_url=settings.upstream_base,
        max_response_bytes=settings.max_response_bytes,
        dict_timeout=settings.upstream_dict_timeout,
    )
    return ScheduleService(settings, store, client, abbreviator, bells), http


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.api_tokens:
        logger.warning("API_TOKENS is empty: every request will be rejected with 401")

    service, http = build_service(settings)
    app.state.settings = settings
    app.state.service = service
    app.state.http = http
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)

    scheduler = SyncScheduler(service, settings)
    app.state.scheduler = scheduler
    # Startup does not await the first fetch: it takes seconds per group and
    # would make the container healthcheck flap on every restart.
    await scheduler.start()
    logger.info(
        "band-schedule %s ready; groups=%s tz=%s interval=%dh",
        __version__,
        settings.groups,
        settings.tz,
        settings.fetch_interval_hours,
    )

    try:
        yield
    finally:
        await scheduler.stop()
        await http.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="band-schedule",
        version=__version__,
        description="OmSU class schedule for Xiaomi Smart Band 10",
        lifespan=lifespan,
    )
    app.include_router(schedule.router)
    app.include_router(calendar.router)
    app.include_router(misc.router)
    return app


app = create_app()
