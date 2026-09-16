"""HTTP layer: auth, ETag/304, calendar, health, admin.

The app is built by hand instead of importing app.main so that `now` stays
injected and the background scheduler never runs during tests.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import calendar, misc, schedule
from app.config import get_settings
from app.deps import get_service
from app.security import RateLimiter
from app.service import ScheduleService
from tests.conftest import ADMIN_TOKEN, NOW, OTHER_TOKEN, TOKEN


@pytest.fixture
def client(settings, loaded_service: ScheduleService):
    app = FastAPI()
    app.include_router(schedule.router)
    app.include_router(calendar.router)
    app.include_router(misc.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_service] = lambda: loaded_service
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.service = loaded_service
    with TestClient(app) as test_client:
        yield test_client


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------------- schedule


def test_schedule_with_bearer(client) -> None:
    response = client.get("/api/v1/schedule?group=5028&days=14", headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["gid"] == 5028
    assert body["g"] == "МБС-301-О-01"
    assert set(body) == {"v", "gid", "g", "gen", "src", "stale", "h", "days"}


def test_schedule_with_query_token(client) -> None:
    response = client.get(f"/api/v1/schedule?group=5028&token={TOKEN}")
    assert response.status_code == 200


def test_etag_equals_hash(client) -> None:
    response = client.get("/api/v1/schedule?group=5028", headers=auth())
    assert response.headers["etag"] == f'"{response.json()["h"]}"'
    assert response.headers["x-schedule-stale"] == "0"


def test_if_none_match_returns_304(client) -> None:
    first = client.get("/api/v1/schedule?group=5028", headers=auth())
    second = client.get(
        "/api/v1/schedule?group=5028",
        headers={**auth(), "If-None-Match": first.headers["etag"]},
    )
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == first.headers["etag"]


def test_stale_data_is_always_sent_in_full(client, settings) -> None:
    """`stale` is not in the hash, so a 304 would hide it from the client."""
    first = client.get("/api/v1/schedule?group=5028", headers=auth())
    settings.frozen_now = NOW + dt.timedelta(hours=12)

    second = client.get(
        "/api/v1/schedule?group=5028",
        headers={**auth(), "If-None-Match": first.headers["etag"]},
    )
    assert second.status_code == 200
    assert second.json()["stale"] is True
    assert second.headers["x-schedule-stale"] == "1"


def test_subgroups_get_different_etags(client) -> None:
    one = client.get("/api/v1/schedule?group=5028&days=21&subgroup=1", headers=auth())
    two = client.get("/api/v1/schedule?group=5028&days=21&subgroup=2", headers=auth())
    assert one.headers["etag"] != two.headers["etag"]


def test_unknown_group_is_rejected(client) -> None:
    assert client.get("/api/v1/schedule?group=9999", headers=auth()).status_code == 400


@pytest.mark.parametrize("days", [0, -1, 22, 999])
def test_days_out_of_range_is_rejected(client, days: int) -> None:
    response = client.get(f"/api/v1/schedule?group=5028&days={days}", headers=auth())
    assert response.status_code == 422


def test_missing_snapshot_returns_503(client, loaded_service) -> None:
    loaded_service.store._snapshots.clear()
    response = client.get("/api/v1/schedule?group=5028", headers=auth())
    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"


# --------------------------------------------------------------------- auth


def test_missing_token_is_401(client) -> None:
    response = client.get("/api/v1/schedule?group=5028")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_wrong_token_is_401(client) -> None:
    assert client.get("/api/v1/schedule?group=5028", headers=auth("nope")).status_code == 401


def test_second_token_also_works(client) -> None:
    assert client.get("/api/v1/schedule?group=5028", headers=auth(OTHER_TOKEN)).status_code == 200


def test_rate_limit_kicks_in(settings, loaded_service) -> None:
    app = FastAPI()
    app.include_router(schedule.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_service] = lambda: loaded_service
    app.state.limiter = RateLimiter(limit=3)

    with TestClient(app) as test_client:
        for _ in range(3):
            assert test_client.get("/api/v1/schedule?group=5028", headers=auth()).status_code == 200
        blocked = test_client.get("/api/v1/schedule?group=5028", headers=auth())
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1
        # A different token has its own budget.
        assert (
            test_client.get("/api/v1/schedule?group=5028", headers=auth(OTHER_TOKEN)).status_code
            == 200
        )


# ----------------------------------------------------------------- calendar


def test_calendar_content_type_and_filename(client) -> None:
    response = client.get(f"/api/v1/calendar/5028.ics?token={TOKEN}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "5028.ics" in response.headers["content-disposition"]


def test_calendar_parses_and_uses_bell_times(client) -> None:
    from icalendar import Calendar

    body = client.get(f"/api/v1/calendar/5028.ics?token={TOKEN}").content
    cal = Calendar.from_ical(body)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert events

    starts = {e.decoded("dtstart").strftime("%H:%M") for e in events}
    # Every event must start at a bell time, not at some API-provided value.
    assert starts <= {"08:45", "10:30", "12:45", "14:30", "16:15", "18:00", "19:45", "21:30"}

    assert cal.get("X-WR-TIMEZONE") == "Asia/Omsk"
    assert any(c.name == "VTIMEZONE" for c in cal.walk()), "Apple Calendar needs VTIMEZONE"


def test_calendar_includes_past_days(client) -> None:
    from icalendar import Calendar

    cal = Calendar.from_ical(client.get(f"/api/v1/calendar/5028.ics?token={TOKEN}").content)
    dates = {e.decoded("dtstart").date() for e in cal.walk() if e.name == "VEVENT"}
    assert min(dates) < NOW.date(), "the .ics feed keeps history the JSON endpoint drops"


def test_calendar_uids_are_stable(client) -> None:
    from icalendar import Calendar

    def uids() -> set[str]:
        cal = Calendar.from_ical(client.get(f"/api/v1/calendar/5028.ics?token={TOKEN}").content)
        return {str(e["UID"]) for e in cal.walk() if e.name == "VEVENT"}

    assert uids() == uids()


def test_calendar_subgroup_filter(client) -> None:
    from icalendar import Calendar

    cal = Calendar.from_ical(
        client.get(f"/api/v1/calendar/5028.ics?token={TOKEN}&subgroup=1").content
    )
    descriptions = [str(e.get("DESCRIPTION", "")) for e in cal.walk() if e.name == "VEVENT"]
    assert not any("Подгруппа: 2" in d for d in descriptions)


def test_calendar_requires_a_token(client) -> None:
    assert client.get("/api/v1/calendar/5028.ics").status_code == 401


def test_calendar_events_carry_a_reminder(client):
    """Напоминание — единственный способ показать пару на браслете, когда
    bluetooth-сессию держит Mi Fitness: оно поднимает уведомление на телефоне,
    а Mi Fitness зеркалит уведомления на экран. Подробности — в DECISIONS.md."""
    from icalendar import Calendar

    cal = Calendar.from_ical(client.get(f"/api/v1/calendar/5028.ics?token={TOKEN}").content)
    events = [c for c in cal.walk("VEVENT")]
    assert events

    for event in events:
        alarms = list(event.walk("VALARM"))
        assert len(alarms) == 1, "у каждой пары ровно одно напоминание"
        alarm = alarms[0]
        assert alarm["action"] == "DISPLAY"
        assert alarm["trigger"].dt == dt.timedelta(minutes=-10)
        # На браслете видна только эта строка, поэтому в ней должно быть место.
        assert str(event["summary"]).split(" (")[0] in str(alarm["description"])


# ------------------------------------------------------- bells, health, admin


def test_bells_endpoint_matches_the_shared_file(client, bells) -> None:
    response = client.get("/api/v1/bells", headers=auth())
    assert response.status_code == 200
    assert response.json() == bells.raw


def test_health_needs_no_token(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_is_200_even_when_upstream_is_broken(client, loaded_service) -> None:
    """A failing university must not make the container restart itself."""
    loaded_service.store._snapshots.clear()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_admin_refresh_requires_its_own_token(client) -> None:
    assert client.post("/api/v1/admin/refresh?group=5028").status_code == 401
    assert client.post("/api/v1/admin/refresh?group=5028", headers=auth(TOKEN)).status_code == 401


def test_admin_refresh_triggers_a_sync(client, loaded_service) -> None:
    before = loaded_service.client.calls
    response = client.post("/api/v1/admin/refresh?group=5028", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 200
    assert loaded_service.client.calls == before + 1
    assert response.json()["group"] == 5028


def test_admin_refresh_reports_upstream_failure(client, loaded_service) -> None:
    from app.errors import UpstreamError

    loaded_service.client.error = UpstreamError("down")
    response = client.post("/api/v1/admin/refresh?group=5028", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 502


def test_admin_disabled_without_a_configured_token(settings, loaded_service) -> None:
    settings.admin_token = ""
    app = FastAPI()
    app.include_router(misc.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_service] = lambda: loaded_service
    app.state.limiter = RateLimiter(60)
    with TestClient(app) as test_client:
        assert test_client.post("/api/v1/admin/refresh?group=5028").status_code == 503
