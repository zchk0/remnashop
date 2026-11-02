"""Shared HTTP client with bounded failover for the v2 and v3 panel integrations."""

from collections.abc import Sequence
from typing import Any

import httpx
from loguru import logger

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
_NETWORK_ERRORS = (
    *_CONNECT_ERRORS,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
)
_UNAVAILABLE_STATUSES = frozenset({502, 503, 504})


class RemnawaveFailoverClient(httpx.AsyncClient):
    def __init__(self, urls: Sequence[str], **kwargs: Any) -> None:
        if not urls:
            raise ValueError("At least one Remnawave URL is required")
        self._panel_urls = tuple(httpx.URL(f"{url.rstrip('/')}/api/") for url in urls)
        self._preferred_index = 0
        super().__init__(base_url=self._panel_urls[0], **kwargs)

    async def send(
        self, request: httpx.Request, *, stream: bool = False, **kwargs: Any
    ) -> httpx.Response:
        primary = self._panel_urls[0]
        if (request.url.scheme, request.url.host, request.url.port) != (
            primary.scheme,
            primary.host,
            primary.port,
        ) or not request.url.raw_path.startswith(primary.raw_path):
            return await super().send(request, stream=stream, **kwargs)

        content = await request.aread()
        suffix = request.url.raw_path[len(primary.raw_path) :]
        start = self._preferred_index
        count = len(self._panel_urls)
        safe_to_replay = request.method in _SAFE_METHODS

        for attempt in range(count):
            index = (start + attempt) % count
            base_url = self._panel_urls[index]
            headers = request.headers.copy()
            # Rebuild Host for the selected domain, including its port if present.
            headers.pop("host", None)
            if base_url.scheme == "http":
                headers["x-forwarded-proto"] = "https"
                headers["x-forwarded-for"] = "127.0.0.1"
            else:
                headers.pop("x-forwarded-proto", None)
                headers.pop("x-forwarded-for", None)
            current = httpx.Request(
                request.method,
                base_url.copy_with(raw_path=base_url.raw_path + suffix),
                headers=headers,
                content=content,
                extensions=dict(request.extensions),
            )
            try:
                response = await super().send(current, stream=stream, **kwargs)
            except _NETWORK_ERRORS as error:
                error.request = current
                self._preferred_index = (index + 1) % count
                # A lost write response does not mean the operation was not applied.
                if attempt + 1 == count or not (
                    safe_to_replay or isinstance(error, _CONNECT_ERRORS)
                ):
                    raise
                self._log_failover(index, count, type(error).__name__)
                continue

            if response.status_code in _UNAVAILABLE_STATUSES:
                self._preferred_index = (index + 1) % count
                if safe_to_replay and attempt + 1 < count:
                    await response.aclose()
                    self._log_failover(index, count, f"HTTP {response.status_code}")
                    continue
            else:
                self._preferred_index = index
            return response

        raise AssertionError("Remnawave failover attempts exhausted")

    @staticmethod
    def _log_failover(index: int, count: int, reason: str) -> None:
        logger.warning(
            "Remnawave endpoint {}/{} unavailable ({}); trying endpoint {}/{}",
            index + 1,
            count,
            reason,
            (index + 1) % count + 1,
            count,
        )
