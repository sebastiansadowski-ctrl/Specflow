"""API projektu: polecenia do skrzynki, odpowiedzi 409, SSE, artefakty, nagłówki bezpieczeństwa."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runtime_helpers import TO_SPEC_GATE, drain, make_runtime, to_building
from specflow.runtime import Runtime
from specflow.settings import Settings
from specflow.web.app import CSP, create_app


@pytest.fixture
def env(tmp_path: Path) -> tuple[TestClient, Runtime]:
    rt, _ = make_runtime(tmp_path)
    app = create_app(Settings(data_dir=tmp_path), runtime=rt, start_workers=False)
    return TestClient(app), rt


def created(client: TestClient, rt: Runtime) -> int:
    response = client.post("/api/projects", json={"name": "Lista zadań"})
    assert response.status_code == 201
    pid = int(response.json()["id"])
    drain(rt, pid)
    return pid


def test_create_project_starts_the_interview(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    state = client.get(f"/api/projects/{pid}").json()
    assert state["phase"] == "constitution" and state["phase_label"] == "Zasady"
    assert state["progress"] == [0, 2] and state["busy"] is False
    [first] = client.get(f"/api/projects/{pid}/messages").json()
    assert first["role"] == "assistant" and first["html"].startswith("<p>")
    assert client.get("/api/projects").json()[0]["id"] == pid


def test_chat_commands_are_queued_one_at_a_time(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    sent = client.post(f"/api/projects/{pid}/messages", json={"text": "Nie"})
    assert sent.status_code == 202 and sent.json()["status"] == "queued"
    assert client.get(f"/api/projects/{pid}").json()["busy"] is True
    second = client.post(f"/api/projects/{pid}/messages", json={"text": "I jeszcze to"})
    assert second.status_code == 409
    drain(rt, pid)
    assert client.post(f"/api/projects/{pid}/messages", json={"text": "Tak"}).status_code == 202


def test_impossible_commands_get_409_or_404(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    assert client.post(f"/api/projects/{pid}/approve").status_code == 409
    assert client.post(f"/api/projects/{pid}/pause").status_code == 409
    answer = client.post(f"/api/projects/{pid}/tasks/T001/answer", json={"text": "x"})
    assert answer.status_code == 404
    assert client.post(f"/api/projects/{pid}/messages", json={"text": ""}).status_code == 422
    assert client.get("/api/projects/999").status_code == 404


def test_gate_summary_and_tasks_after_planning(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    for text in TO_SPEC_GATE:
        client.post(f"/api/projects/{pid}/messages", json={"text": text})
        drain(rt, pid)
    state = client.get(f"/api/projects/{pid}").json()
    assert (
        state["gate"] == "spec" and "<strong>Dodawanie zadań</strong>" in state["gate_summary_html"]
    )
    assert client.post(f"/api/projects/{pid}/approve").status_code == 202
    drain(rt, pid)
    client.post(f"/api/projects/{pid}/messages", json={"text": "Wymagany"})
    drain(rt, pid)
    client.post(f"/api/projects/{pid}/approve")
    drain(rt, pid, max_steps=1)
    tasks = client.get(f"/api/projects/{pid}/tasks").json()
    assert [t["key"] for t in tasks] == ["T001", "T002", "T003", "T004", "T005"]
    assert client.get(f"/api/projects/{pid}").json()["run_state"] == "running"
    assert client.post(f"/api/projects/{pid}/pause").status_code == 202
    answer = client.post(f"/api/projects/{pid}/tasks/T001/answer", json={"text": "x"})
    assert answer.status_code == 409  # zadanie nie czeka na odpowiedź


def test_sse_backlog_respects_last_event_id(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    url = f"/api/projects/{pid}/events?follow=false"
    response = client.get(url)
    assert response.headers["content-type"].startswith("text/event-stream")
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert len(ids) >= 3
    tail = client.get(url, headers={"Last-Event-ID": str(ids[-2])}).text
    assert [int(line[4:]) for line in tail.splitlines() if line.startswith("id: ")] == ids[-1:]
    assert '"narration": {"text": "Projekt utworzony."' in response.text


def test_artifacts_are_listed_and_rendered_safely(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    to_building(rt, pid)
    listed = client.get(f"/api/projects/{pid}/artifacts").json()
    paths = [a["path"] for a in listed]
    assert paths[0] == ".specify/memory/constitution.md"
    assert "specs/001-lista-zadan/spec.md" in paths and "specs/001-lista-zadan/tasks.md" in paths

    with rt.sessions() as session:
        root = rt.workspace(rt.store(session, pid).get_project(pid)).path
    spec = root / "specs/001-lista-zadan/spec.md"
    spec.write_text(spec.read_text() + "\n<script>alert(1)</script>\n[x](javascript:alert(1))\n")
    html = client.get(f"/api/projects/{pid}/artifacts/specs/001-lista-zadan/spec.md").json()["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript:' not in html


def test_artifact_paths_outside_the_allowlist_are_rejected(
    env: tuple[TestClient, Runtime], tmp_path: Path
) -> None:
    client, rt = env
    pid = created(client, rt)
    to_building(rt, pid)
    with rt.sessions() as session:
        root = rt.workspace(rt.store(session, pid).get_project(pid)).path
    secret = tmp_path / "secret.txt"
    secret.write_text("SPECFLOW_TOKEN=abc")
    plan = root / "specs/001-lista-zadan/plan.md"
    plan.unlink()
    os.symlink(secret, plan)  # agent podkłada dowiązanie do pliku poza workspace

    base = f"/api/projects/{pid}/artifacts"
    assert "specs/001-lista-zadan/plan.md" not in [a["path"] for a in client.get(base).json()]
    for path in ("specs/001-lista-zadan/plan.md", "../secret.txt", "pyproject.toml"):
        assert client.get(f"{base}/{path}").status_code == 404


def test_security_headers_on_every_response(env: tuple[TestClient, Runtime]) -> None:
    client, _ = env
    for url in ("/", "/health", "/api/projects", "/static/app.css"):
        headers = client.get(url).headers
        assert headers["content-security-policy"] == CSP
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in CSP and "unsafe-inline" not in CSP
