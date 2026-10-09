"""Client for the NexusPlan Home Assistant link API (/api/ha-link/*).

Every call is OUTBOUND from Home Assistant to NexusPlan. NexusPlan never
connects to Home Assistant, so the home needs no remote access and NexusPlan
holds no credential to it. The only secret is the link token NexusPlan issued,
scoped to one project.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class NexusPlanError(Exception):
    """Base error."""


class NexusPlanConnectionError(NexusPlanError):
    """NexusPlan could not be reached, or answered with a server error."""


class NexusPlanAuthError(NexusPlanError):
    """The link token is no longer valid — the person must pair again."""


class NexusPlanInvalidCodeError(NexusPlanError):
    """The pairing code was wrong, expired or already used."""


class NexusPlanRateLimitedError(NexusPlanConnectionError):
    """Too many requests — NexusPlan asked us to wait (HTTP 429)."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        #: Seconds NexusPlan asked us to wait (its Retry-After header), if given.
        self.retry_after = retry_after


class NexusPlanClient:
    """A NexusPlan project, as seen through one link token."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, token: str | None = None) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._token = token

    async def _request(self, method: str, path: str, json: Any = None) -> Any:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method, f"{self._base}{path}", json=json, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = None
                code = (body or {}).get("code") if isinstance(body, dict) else None
                if resp.status == 401:
                    raise NexusPlanAuthError((body or {}).get("error", "Unauthorized"))
                if resp.status == 429:
                    try:
                        retry_after: int | None = int(resp.headers.get("Retry-After", ""))
                    except ValueError:
                        retry_after = None
                    raise NexusPlanRateLimitedError((body or {}).get("error", "Too many requests"), retry_after)
                if resp.status == 400 and code == "invalid_code":
                    raise NexusPlanInvalidCodeError(body.get("error"))
                if resp.status >= 400:
                    msg = (body or {}).get("error") if isinstance(body, dict) else None
                    raise NexusPlanConnectionError(f"HTTP {resp.status}: {msg or getattr(resp, 'reason', '') or 'error'}")
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise NexusPlanConnectionError(str(err) or type(err).__name__) from err

    async def pair(self, code: str, instance: dict[str, Any]) -> dict[str, Any]:
        """Exchange a pairing code for a link token and the project it belongs to."""
        return await self._request("POST", "/api/ha-link/pair", {"code": code, "instance": instance})

    async def me(self) -> dict[str, Any]:
        return await self._request("GET", "/api/ha-link/me")

    async def put_registry(self, registry: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", "/api/ha-link/registry", registry)

    async def post_signals(self, readings: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", "/api/ha-link/signals", {"readings": readings})

    async def get_map(self) -> dict[str, Any]:
        return await self._request("GET", "/api/ha-link/map")
