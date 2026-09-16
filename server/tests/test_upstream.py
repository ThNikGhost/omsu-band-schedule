"""OmsuClient and retry, against mocked HTTP only."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.errors import DataExtractionError, UpstreamError
from app.upstream.omsu import OmsuClient, build_client
from app.upstream.retry import RetryConfig, calculate_delay, retry_async

BASE = "https://eservice.omsu.ru/schedule/backend"
URL = f"{BASE}/schedule/group/5028"
OK = {"success": True, "message": "ok", "data": [{"day": "16.09.2026", "lessons": []}]}


@pytest.fixture
async def client():
    http = build_client()
    try:
        yield OmsuClient(
            http,
            base_url=BASE,
            max_response_bytes=4096,
            # No real sleeping in tests; backoff timing is covered separately.
            retry_config=RetryConfig(max_attempts=3, base_delay=0.0, jitter=0.0),
        )
    finally:
        await http.aclose()


@respx.mock
async def test_fetch_parses_envelope(client: OmsuClient) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=OK))
    assert await client.fetch_group(5028) == OK


@respx.mock
async def test_retries_503_then_succeeds(client: OmsuClient) -> None:
    route = respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json=OK)])
    assert await client.fetch_group(5028) == OK
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_max_attempts(client: OmsuClient) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(504))
    with pytest.raises(UpstreamError, match="504"):
        await client.fetch_group(5028)
    assert route.call_count == 3


@respx.mock
async def test_does_not_retry_404(client: OmsuClient) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(UpstreamError, match="404"):
        await client.fetch_group(5028)
    assert route.call_count == 1


@respx.mock
async def test_timeout_is_retried_then_reported(client: OmsuClient) -> None:
    route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamError, match="ReadTimeout"):
        await client.fetch_group(5028)
    assert route.call_count == 3


@respx.mock
async def test_sends_user_agent(client: OmsuClient) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=OK))
    await client.fetch_group(5028)
    assert "band-schedule" in route.calls[0].request.headers["user-agent"]


@respx.mock
async def test_oversized_body_is_rejected(client: OmsuClient) -> None:
    """A runaway response must not be buffered into memory in full."""
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(UpstreamError, match="exceeds"):
        await client.fetch_group(5028)


@respx.mock
async def test_non_json_body_raises(client: OmsuClient) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"<html>504</html>"))
    with pytest.raises(DataExtractionError, match="non-JSON"):
        await client.fetch_group(5028)


@respx.mock
async def test_dict_endpoint_504_is_reported(client: OmsuClient) -> None:
    """The real /dict/groups answers 504 every time; the CLI must see that clearly."""
    respx.get(f"{BASE}/dict/groups").mock(return_value=httpx.Response(504, content=b"gateway"))
    with pytest.raises(UpstreamError, match="504"):
        await client.fetch_dict("groups")


def test_backoff_grows_and_is_capped() -> None:
    config = RetryConfig(base_delay=1.0, max_delay=8.0, jitter=0.0)
    delays = [calculate_delay(i, config) for i in range(5)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_jitter_stays_within_bounds() -> None:
    config = RetryConfig(base_delay=10.0, max_delay=100.0, jitter=0.25)
    assert calculate_delay(0, config, rand=lambda: 0.0) == pytest.approx(7.5)
    assert calculate_delay(0, config, rand=lambda: 1.0) == pytest.approx(12.5)


async def test_retry_reraises_non_retryable() -> None:
    async def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await retry_async(boom, config=RetryConfig(max_attempts=3, base_delay=0))
