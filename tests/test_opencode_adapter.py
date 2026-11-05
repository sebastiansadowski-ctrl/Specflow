"""Adapter OpenCode na udawanym serwerze HTTP (httpx.MockTransport) - bez prawdziwego OpenCode."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from specflow.harness import (
    AgentEvent,
    AgentProfile,
    FileChanged,
    RunFinished,
    SessionSpec,
    TextPrompt,
)
from specflow.harness.opencode import OpenCodeClient, OpenCodeHarness

SID = "ses_abc"


def sse(*envelopes: dict[str, Any]) -> bytes:
    chunks = [f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in envelopes]
    return "".join(chunks).encode()


def ev(kind: str, **data: Any) -> dict[str, Any]:
    return {"id": "e", "type": kind, "created": 0, "data": {"sessionID": SID, **data}}


class FakeServer:
    def __init__(self, stream: bytes | None = None) -> None:
        self.stream = stream
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/session" and request.method == "POST":
            return httpx.Response(200, json={"data": {"id": SID}})
        if request.url.path == "/api/event":
            if self.stream is None:
                return httpx.Response(200, content=_never_ending())
            return httpx.Response(200, content=self.stream)
        return httpx.Response(200, json={"data": {}})


async def _never_ending() -> AsyncIterator[bytes]:
    yield b": connected\n\n"
    await asyncio.sleep(3600)


def make_harness(server: FakeServer, root: Path) -> OpenCodeHarness:
    http = httpx.AsyncClient(base_url="http://opencode", transport=httpx.MockTransport(server))
    return OpenCodeHarness(OpenCodeClient(http=http), host_root=root, container_root="/workspace")


def run(server: FakeServer, root: Path, timeout_s: float = 5) -> list[AgentEvent]:
    async def go() -> list[AgentEvent]:
        harness = make_harness(server, root)
        workdir = root / "0001-demo"
        workdir.mkdir(exist_ok=True)
        spec = SessionSpec(title="T001", workdir=workdir, profile=AgentProfile.IMPLEMENTER)
        session = await harness.start_session(spec)
        prompt = TextPrompt(text="Zadanie T001")
        return [e async for e in harness.run(session, prompt, timeout_s=timeout_s)]

    return asyncio.run(go())


def test_session_is_created_in_container_path_with_profile_rules(tmp_path: Path) -> None:
    server = FakeServer(sse(ev("session.execution.succeeded")))
    run(server, tmp_path)
    method, path, body = server.requests[0]
    assert (method, path) == ("POST", "/api/session")
    assert body is not None
    assert body["location"] == {"directory": "/workspace/0001-demo"}
    assert {"action": "edit", "resource": "tests/**", "effect": "deny"} in body["permissions"]
    assert ("POST", f"/api/session/{SID}/prompt", {"text": "Zadanie T001"}) in server.requests


def test_run_maps_events_relativizes_paths_and_parses_report(tmp_path: Path) -> None:
    report = '```json\n{"status": "done", "summary": "ok", "notes": "n"}\n```'
    server = FakeServer(
        sse(
            ev("session.tool.input.started", id="c1", name="write"),
            ev("session.tool.called", id="c1", input={"filePath": "/workspace/0001-demo/src/a.py"}),
            ev("session.tool.success", id="c1", content=[{"type": "text", "text": "ok"}]),
            ev("session.text.ended", text=report),
            ev("session.execution.succeeded"),
            ev("session.idle"),
        )
    )
    events = run(server, tmp_path)
    assert [e.path for e in events if isinstance(e, FileChanged)] == ["src/a.py"]
    last = events[-1]
    assert isinstance(last, RunFinished) and last.status == "completed"
    assert last.report is not None and last.report.notes == "n"


def test_timeout_interrupts_session(tmp_path: Path) -> None:
    server = FakeServer(stream=None)
    events = run(server, tmp_path, timeout_s=0.2)
    last = events[-1]
    assert isinstance(last, RunFinished) and last.status == "timeout"
    assert ("POST", f"/api/session/{SID}/interrupt", None) in server.requests


def test_stream_ending_without_terminal_event_is_a_failure(tmp_path: Path) -> None:
    server = FakeServer(sse(ev("session.text.ended", text="...")))
    last = run(server, tmp_path)[-1]
    assert isinstance(last, RunFinished) and last.status == "failed"
