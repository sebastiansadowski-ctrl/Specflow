"""Minimalny klient HTTP API OpenCode v2.2.5 (`/api/...`)."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from specflow.harness.base import HarnessError


class OpenCodeClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4096",
        *,
        password: str | None = None,
        username: str = "opencode",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        auth = httpx.BasicAuth(username, password) if password else None
        self._http = http or httpx.AsyncClient(base_url=base_url, auth=auth, timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        try:
            response = await self._http.post(path, json=body)
        except httpx.HTTPError as exc:
            raise HarnessError(f"OpenCode niedostępny ({path}): {exc}") from exc
        if response.status_code >= 400:
            raise HarnessError(f"OpenCode {path} -> {response.status_code}: {response.text[:300]}")
        return response

    async def create_session(
        self, *, title: str, directory: str, permissions: list[dict[str, str]]
    ) -> str:
        response = await self._post(
            "/api/session",
            {"title": title, "location": {"directory": directory}, "permissions": permissions},
        )
        return str(response.json()["data"]["id"])

    async def prompt(self, session_id: str, text: str) -> None:
        await self._post(f"/api/session/{session_id}/prompt", {"text": text})

    async def command(self, session_id: str, name: str, arguments: str) -> None:
        await self._post(f"/api/session/{session_id}/command", {"name": name, "text": arguments})

    async def interrupt(self, session_id: str) -> None:
        await self._post(f"/api/session/{session_id}/interrupt")

    async def delete_session(self, session_id: str) -> None:
        try:
            await self._http.delete(f"/api/session/{session_id}")
        except httpx.HTTPError as exc:
            raise HarnessError(f"Nie udało się usunąć sesji {session_id}: {exc}") from exc

    @asynccontextmanager
    async def events(self, types: list[str]) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """Otwiera strumień SSE. Połączenie jest gotowe po wejściu do kontekstu,
        więc prompt wysłany wewnątrz nie zgubi pierwszych zdarzeń."""
        params = [("types", t) for t in types]
        try:
            async with self._http.stream(
                "GET", "/api/event", params=params, timeout=None
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise HarnessError(f"OpenCode /api/event -> {response.status_code}")
                yield _parse_sse(response.aiter_lines())
        except httpx.HTTPError as exc:
            raise HarnessError(f"Strumień zdarzeń OpenCode przerwany: {exc}") from exc


async def _parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """Składa zdarzenia SSE (`event:` / `data:` / pusta linia) i dekoduje JSON z `data`."""
    data_lines: list[str] = []
    async for line in lines:
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                data_lines = []
                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(envelope, dict):
                    yield envelope
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
