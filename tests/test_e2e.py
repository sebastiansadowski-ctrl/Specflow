"""End-to-end przez cały stos: HTTP → skrzynka → workery w tle (supervisor) → SSE.

W odróżnieniu od test_runtime nikt tu nie woła workera ręcznie: działa tak jak na serwerze.
Harness to nagrane demo (Mock), ale testy i weryfikacja zadań są prawdziwe.
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from runtime_helpers import TO_SPEC_GATE, make_runtime
from specflow.settings import Settings
from specflow.web.app import create_app

TIMEOUT_S = 90.0


def wait(client: TestClient, url: str, check: Callable[[Any], bool]) -> Any:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        data = client.get(url).json()
        if check(data):
            return data
        time.sleep(0.05)
    raise AssertionError(f"{url}: warunek niespełniony, ostatni stan: {data}")


def test_full_stack_from_new_project_to_done(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    app = create_app(Settings(data_dir=tmp_path), runtime=rt, start_workers=True)

    with TestClient(app) as client:  # lifespan: supervisor startuje workery
        pid = client.post("/api/projects", json={"name": "Lista zadań"}).json()["id"]
        state = f"/api/projects/{pid}"
        idle: Callable[[Any], bool] = lambda s: not s["busy"]  # noqa: E731

        wait(client, f"{state}/messages", lambda m: len(m) == 1)
        for text in TO_SPEC_GATE:
            assert client.post(f"{state}/messages", json={"text": text}).status_code == 202
            wait(client, state, idle)
        assert wait(client, state, idle)["gate"] == "spec"

        client.post(f"{state}/approve")
        assert wait(client, state, lambda s: s["phase"] == "clarify" and idle(s))
        client.post(f"{state}/messages", json={"text": "Tytuł jest wymagany"})
        wait(client, state, lambda s: s["gate"] == "plan")

        client.post(f"{state}/approve")
        done = wait(client, state, lambda s: s["phase"] == "done")
        assert done["run_state"] == "idle"
        tasks = client.get(f"{state}/tasks").json()
        assert [t["status"] for t in tasks] == ["done"] * 5

        stream = client.get(f"{state}/events?follow=false").text
        assert stream.count('"to_status": "done"') == 5
        assert "Aplikacja jest gotowa" in client.get(f"{state}/messages").text
