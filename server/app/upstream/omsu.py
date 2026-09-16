"""HTTP client for the OmSU schedule API.

Endpoint and envelope shape follow reference/studyhelper/omsu_parser.py. Changes
driven by measurements on the live API (see docs/DECISIONS.md):
  * read timeout 60s, not 30s - the response is 1.5 MB and the server is slow;
  * follow_redirects and an explicit User-Agent;
  * the body is streamed with a hard size cap, so a runaway response cannot OOM
    the container before we ever look at it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.errors import DataExtractionError, UpstreamError
from app.upstream.retry import RetryConfig, retry_async

logger = logging.getLogger(__name__)

USER_AGENT = "band-schedule/1.0 (+https://github.com/; personal use)"

SCHEDULE_PATH = "/schedule/group/{group_id}"
# Used by the university frontend (found in app.1fd8a6a9.js). Currently answers
# 504 every time, so find-group treats it as best-effort only.
DICT_PATH = "/dict/{kind}"


def build_client(
    *,
    connect_timeout: float = 10.0,
    read_timeout: float = 60.0,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=connect_timeout,
            pool=connect_timeout,
        ),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


class OmsuClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://eservice.omsu.ru/schedule/backend",
        max_response_bytes: int = 16 * 1024 * 1024,
        dict_timeout: float = 120.0,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._max_bytes = max_response_bytes
        self._dict_timeout = dict_timeout
        self._retry = retry_config or RetryConfig(max_attempts=3, base_delay=2.0, max_delay=20.0)

    async def fetch_group(self, group_id: int) -> dict[str, Any]:
        """Full schedule history for one group. About 1.5 MB, ~5 s."""
        url = self._base + SCHEDULE_PATH.format(group_id=group_id)
        payload = await self._get_json_with_retry(url)
        if not isinstance(payload, dict):
            raise DataExtractionError("upstream response is not a JSON object")
        return payload

    async def fetch_dict(self, kind: str) -> Any:
        """Dictionary of groups / tutors / auditories. Usually times out (504)."""
        url = self._base + DICT_PATH.format(kind=kind)
        return await self._get_json_with_retry(url, request_timeout=self._dict_timeout)

    async def _get_json_with_retry(self, url: str, *, request_timeout: float | None = None) -> Any:
        """Retry transport errors and 429/502/503/504, then translate failures."""
        try:
            return await retry_async(
                self._get_json,
                url,
                request_timeout=request_timeout,
                config=self._retry,
            )
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(f"{url} returned HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise UpstreamError(f"request to {url} failed: {type(exc).__name__}: {exc}") from exc

    async def _get_json(self, url: str, *, request_timeout: float | None = None) -> Any:
        """One attempt. Transport errors propagate untouched so retry can see them."""
        kwargs: dict[str, Any] = {}
        if request_timeout is not None:
            kwargs["timeout"] = request_timeout

        async with self._client.stream("GET", url, **kwargs) as response:
            if response.status_code >= httpx.codes.BAD_REQUEST:
                await response.aread()
                response.raise_for_status()

            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._max_bytes:
                    raise UpstreamError(f"response from {url} exceeds {self._max_bytes} bytes")
                chunks.append(chunk)

        body = b"".join(chunks)
        try:
            return json.loads(body)
        except ValueError as exc:
            snippet = body[:120].decode("utf-8", "replace")
            raise DataExtractionError(f"upstream returned non-JSON body: {snippet!r}") from exc
