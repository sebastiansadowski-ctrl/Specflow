"""Widoki HTML: ekran zależny od etapu, bramki w czacie, karty zadań, zgodność z CSP."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runtime_helpers import TO_SPEC_GATE, drain, make_runtime, to_building
from specflow.domain import Actor, TaskStatus
from specflow.runtime import Runtime
from specflow.settings import Settings
from specflow.web.app import create_app
from specflow.web.views import REJECTED_HEADER


@pytest.fixture
def env(tmp_path: Path) -> tuple[TestClient, Runtime]:
    rt, _ = make_runtime(tmp_path)
    app = create_app(Settings(data_dir=tmp_path), runtime=rt, start_workers=False)
    return TestClient(app), rt


def created(client: TestClient, rt: Runtime) -> int:
    response = client.post("/projects", data={"name": "Lista zadań"}, follow_redirects=False)
    assert response.status_code == 303
    pid = int(response.headers["location"].rsplit("/", 1)[-1])
    drain(rt, pid)
    return pid


def say(client: TestClient, rt: Runtime, pid: int, text: str) -> str:
    html = client.post(f"/projects/{pid}/chat", data={"text": text}).text
    drain(rt, pid)
    return html


def assert_csp_friendly(html: str) -> None:
    """Bez stylów, skryptów i obsługi zdarzeń inline - CSP by je zablokował."""
    assert " style=" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+=", html)


def test_projects_page_and_form_create_a_project(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    assert "Nie masz jeszcze projektów" in client.get("/").text
    pid = created(client, rt)
    listing = client.get("/").text
    assert f'href="/projects/{pid}"' in listing and "Zasady" in listing
    page = client.get(f"/projects/{pid}").text
    assert 'class="layout mode-chat"' in page and "dane osobowe" in page
    assert '<li class="stage current">Zasady</li>' in page
    assert "Doprecyzowanie" not in page  # etap pokazujemy tylko, gdy są pytania
    assert_csp_friendly(page)


def test_chat_shows_pending_message_and_keeps_text_when_busy(
    env: tuple[TestClient, Runtime],
) -> None:
    client, rt = env
    pid = created(client, rt)
    first = client.post(f"/projects/{pid}/chat", data={"text": "Nie"})
    assert REJECTED_HEADER not in first.headers
    assert 'class="msg user pending"' in first.text and "Asystent pisze" in first.text
    second = client.post(f"/projects/{pid}/chat", data={"text": "I jeszcze to"})
    assert second.headers[REJECTED_HEADER] == "1"  # app.js nie wyczyści pola
    assert "Poczekaj chwilę" in second.text
    drain(rt, pid)
    after = client.get(f"/projects/{pid}/chat").text
    assert "pending" not in after and "urządzeniach" in after


def test_gate_is_a_card_in_the_chat(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    for text in TO_SPEC_GATE:
        html = say(client, rt, pid, text)
    html = client.get(f"/projects/{pid}/chat").text
    assert "Specyfikacja do akceptacji" in html
    assert f'hx-post="/projects/{pid}/approve"' in html
    assert '<label for="composer-text" class="button ghost">Chcę coś zmienić</label>' in html
    assert "<strong>Dodawanie zadań</strong>" in html
    approved = client.post(f"/projects/{pid}/approve").text
    assert "Specyfikacja do akceptacji" not in approved  # karta znika, trwa planowanie
    drain(rt, pid)
    html = client.get(f"/projects/{pid}/chat").text
    assert "✓ Zatwierdzono specyfikację" in html and "pusty tytuł" in html
    assert "Doprecyzowanie" in client.get(f"/projects/{pid}/stages").text


def test_build_mode_shows_board_feed_and_pause(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    to_building(rt, pid)
    page = client.get(f"/projects/{pid}").text
    assert 'class="layout mode-build"' in page and "data-toggle-chat" in page
    assert page.count('data-task-card="') == 5
    assert 'data-status="awaiting_input"' in page and "0 z 5 zrobionych" in page
    assert "Etap: Realizacja" in page  # pasek logu z narracją
    assert_csp_friendly(page)

    board = client.post(f"/projects/{pid}/pause").text
    assert "Budowa trwa" in board  # polecenie czeka w skrzynce
    drain(rt, pid, max_steps=1)
    board = client.get(f"/projects/{pid}/board").text
    assert "Wstrzymane" in board and f'hx-post="/projects/{pid}/resume"' in board


def test_task_card_shows_question_and_accepts_answer(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    to_building(rt, pid)
    with rt.sessions() as session:
        store = rt.store(session, pid)
        store.set_status(pid, "T001", TaskStatus.IN_PROGRESS, Actor.ORCHESTRATOR)
        store.request_input(
            pid, "T001", Actor.ORCHESTRATOR, reason="question", message="Jaki **kolor** listy?"
        )
        store.commit()

    detail = client.get(f"/projects/{pid}/tasks/T001").text
    assert "Agent ma pytanie" in detail and "<strong>kolor</strong>" in detail
    assert f'hx-post="/projects/{pid}/tasks/T001/answer"' in detail
    assert "czeka na Ciebie" in client.get(f"/projects/{pid}/board").text
    answered = client.post(f"/projects/{pid}/tasks/T001/answer", data={"text": "Niebieski"})
    assert REJECTED_HEADER not in answered.headers
    assert "Odpowiedź zapisana" in answered.text
    again = client.post(f"/projects/{pid}/tasks/T002/answer", data={"text": "x"})
    assert again.headers[REJECTED_HEADER] == "1" and "nie czeka na odpowiedź" in again.text
    assert_csp_friendly(detail)


def test_artifact_view_renders_model_text_safely(env: tuple[TestClient, Runtime]) -> None:
    client, rt = env
    pid = created(client, rt)
    to_building(rt, pid)
    with rt.sessions() as session:
        root = rt.workspace(rt.store(session, pid).get_project(pid)).path
    spec = root / "specs/001-lista-zadan/spec.md"
    spec.write_text(
        spec.read_text() + '\n<script>alert(1)</script>\n<img src=x onerror="alert(1)">\n'
    )
    html = client.get(
        f"/projects/{pid}/artifact", params={"path": "specs/001-lista-zadan/spec.md"}
    ).text
    assert "Feature Specification" in html
    assert "<script>" not in html and "<img" not in html and "&lt;script&gt;" in html
    missing = client.get(f"/projects/{pid}/artifact", params={"path": "../../etc/passwd"})
    assert missing.status_code == 404


def test_static_client_script_is_csp_friendly(env: tuple[TestClient, Runtime]) -> None:
    client, _ = env
    script = client.get("/static/app.js").text
    assert "EventSource" in script and "textContent" in script
    assert ".innerHTML" not in script and "eval(" not in script


def test_failed_workspace_setup_leaves_no_broken_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`specify init` nie działa (tu: brak CLI w PATH) → projekt i katalog są sprzątane,
    a użytkownik widzi komunikat narzędzia zamiast błędu 500."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin") + ":/usr/bin:/bin")
    rt, _ = make_runtime(tmp_path)
    settings = Settings(data_dir=tmp_path, spec_kit_init=True)
    client = TestClient(create_app(settings, runtime=rt, start_workers=False))
    page = client.post("/projects", data={"name": "Lista zadań"}, follow_redirects=False)
    api = client.post("/api/projects", json={"name": "Lista zadań"})
    assert page.status_code == 502 and "Nie udało się przygotować projektu" in page.text
    assert "specify init" in page.text
    assert api.status_code == 502 and "specify init" in api.json()["detail"]
    assert client.get("/api/projects").json() == []
    assert not any(rt.projects_dir.iterdir())


def test_artifact_list_refresh_keeps_open_document(env: tuple[TestClient, Runtime]) -> None:
    """Regresja M6b: przyciski dziedziczyły hx-swap="outerHTML" listy, więc pierwszy podgląd
    zastępował #artifact-view, a kolejne kliknięcia kończyły się htmx:targetError; do tego
    odświeżenie listy (sf:artifacts) kasowało otwarty dokument."""
    client, rt = env
    pid = created(client, rt)
    to_building(rt, pid)
    html = client.get(f"/projects/{pid}/artifacts").text
    listing = html.split('<div id="artifacts"', 1)[1].split('<div id="artifact-view"', 1)[0]
    assert 'hx-select="#artifacts"' in listing and 'hx-disinherit="*"' in listing
    assert listing.count('hx-target="#artifact-view" hx-swap="innerHTML"') >= 3
    assert '<div id="artifact-view"' in html.split("</ul>", 1)[1]  # podgląd poza listą
