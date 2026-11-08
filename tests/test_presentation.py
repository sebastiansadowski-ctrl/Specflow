"""Narracja zdarzeń, bezpieczny Markdown, ustawienia i konfiguracja SQLite."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from specflow.__main__ import parse_args
from specflow.settings import Settings
from specflow.storage import make_engine
from specflow.storage.models import EventRow
from specflow.web.markdown import render_markdown
from specflow.web.narration import narrate


def ev(type_: str, key: str | None = None, **payload: Any) -> EventRow:
    return EventRow(
        project_id=1,
        type=type_,
        task_key=key,
        actor="x",
        from_status=payload.pop("old", None),
        to_status=payload.pop("new", None),
        payload=payload,
    )


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            ev("agent_tool_call", "T003", tool="edit", target="app/todos.py"),
            "T003: zmienia plik app/todos.py",
        ),
        (
            ev("agent_tool_call", "T003", tool="read", target="specs/001/spec.md"),
            "T003: czyta plik specs/001/spec.md",
        ),
        (
            ev("agent_tool_call", "T003", tool="bash", target="uv run pytest -q"),
            "T003: uruchamia testy",
        ),
        (
            ev("agent_tool_call", "T003", tool="shell", target="uv run pytest -q"),
            "T003: uruchamia testy",
        ),
        (
            ev("agent_tool_call", "T003", tool="bash", target="uv add httpx"),
            "T003: instaluje zależności",
        ),
        (
            ev("agent_tool_call", "T003", tool="grep", target="TodoList"),
            "T003: przegląda pliki projektu",
        ),
        (ev("status_changed", "T002", old="ready", new="in_progress"), "T002: agent zaczyna pracę"),
        (
            ev("status_changed", "T002", old="rework", new="in_progress"),
            "T002: agent poprawia swoją pracę po weryfikacji",
        ),
        (
            ev(
                "status_changed",
                "T002",
                old="verification",
                new="rework",
                reason="2 testy nie przechodzą",
            ),
            "T002: weryfikacja nie przeszła (2 testy nie przechodzą)",
        ),
        (
            ev("status_changed", "T002", old="verification", new="done"),
            "T002: zrobione, weryfikacja przeszła",
        ),
        (ev("planning_step", step="specify"), "Piszę specyfikację…"),
        (ev("phase_changed", to="building"), "Etap: Realizacja"),
        (ev("gate_opened", gate="plan"), "Plan czeka na Twoją akceptację."),
        (
            ev("recovery", tasks=["T004"]),
            "Specflow uruchomił się ponownie. Przerwane zadania wróciły do kolejki: T004.",
        ),
    ],
)
def test_narration_is_plain_language(event: EventRow, expected: str) -> None:
    narration = narrate(event)
    assert narration is not None and narration.text == expected and narration.level == "main"


def test_technical_events_are_details_or_hidden() -> None:
    message = narrate(ev("agent_message", "T001", text="Myślę, że  trzeba\nzmienić plik."))
    assert message is not None and message.level == "detail"
    assert message.text == "T001: Agent: Myślę, że trzeba zmienić plik."
    assert narrate(ev("agent_usage", "T001", input_tokens=10)) is None
    assert narrate(ev("agent_tool_result", "T001", ok=True)) is None
    assert narrate(ev("chat_message", role="user", text="hej")) is None
    backlog = narrate(ev("status_changed", "T005", old="backlog", new="ready"))
    assert backlog is not None and backlog.level == "detail"


@pytest.mark.parametrize(
    "dangerous",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "[klik](javascript:alert(1))",
        "[klik](JAVASCRIPT:alert(1))",
        "[klik](data:text/html;base64,PHNjcmlwdD4=)",
        '<a href="javascript:alert(1)">x</a>',
        "<iframe src=//evil.example></iframe>",
    ],
)
def test_markdown_never_emits_active_html(dangerous: str) -> None:
    html = render_markdown(dangerous).lower()
    for marker in ("<script", "<img", "<iframe", 'href="javascript', 'href="data:'):
        assert marker not in html


def test_markdown_keeps_formatting_and_safe_links() -> None:
    html = render_markdown(
        "**Given** a\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n[docs](https://x.dev)"
    )
    assert "<strong>Given</strong>" in html and "<table>" in html
    assert '<a href="https://x.dev" rel="noopener noreferrer nofollow">docs</a>' in html


def test_settings_precedence_cli_over_env_over_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # bez .env z katalogu repo
    assert Settings().harness == "mock"
    monkeypatch.setenv("SPECFLOW_HARNESS", "opencode")
    monkeypatch.setenv("SPECFLOW_PORT", "9000")
    from_env = Settings()
    assert from_env.harness == "opencode" and from_env.port == 9000
    assert Settings(**parse_args(["serve", "--harness", "mock"])).harness == "mock"
    assert Settings(**parse_args([])).harness == "opencode"  # brak argumentu = zmienna wygrywa


def test_settings_from_dotenv_and_derived_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SPECFLOW_HARNESS=opencode\nSPECFLOW_DATA_DIR=/data\n")
    settings = Settings()
    assert settings.harness == "opencode"
    assert settings.db_url() == "sqlite:////data/specflow.sqlite3"
    assert settings.projects_path() == Path("/data/projects")
    assert settings.should_init_spec_kit() is True and settings.verification_command() is None
    mock = Settings(harness="mock")
    assert mock.should_init_spec_kit() is False
    assert mock.verification_command() and "-m pytest" in str(mock.verification_command())


def test_sqlite_runs_in_wal_with_full_sync(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'db.sqlite3'}")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar() == 2  # FULL
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
