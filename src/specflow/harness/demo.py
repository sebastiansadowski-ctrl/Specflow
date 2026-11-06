"""Scenariusz demo dla adaptera Mock: "lista zadań", od wywiadu do zrobionych zadań.

Pozwala przeklikać cały Specflow bez modelu (`SPECFLOW_HARNESS=mock`), a w CI służy
za test end-to-end. Odpowiedzi asystenta i praca agenta są NAGRANE: nie zależą od tego,
co wpisze użytkownik. Kod zadań jest prawdziwy, więc weryfikacja (pytest, git, TDD)
działa naprawdę.
"""

import itertools
import json
from collections.abc import Iterator
from typing import Any

from specflow.harness.base import Prompt, Session, TextPrompt
from specflow.harness.mock import MockHarness, Scenario, success
from specflow.interview.prompts import MARKER
from specflow.workspace import Workspace

FEATURE = "specs/001-lista-zadan"
QUESTION = "Czy zadanie może mieć pusty tytuł?"


def _say(**payload: Any) -> Scenario:
    body = json.dumps(payload, ensure_ascii=False)
    return Scenario(name="wywiad", final_text=f"```json\n{body}\n```")


STORIES = [
    {
        "title": "Dodawanie zadań",
        "actor": "użytkownik",
        "action": "dodaje zadanie z tytułem",
        "benefit": "pamięta, co ma zrobić",
        "acceptance": ["nowe zadanie pojawia się na liście"],
    },
    {
        "title": "Oznaczanie jako zrobione",
        "actor": "użytkownik",
        "action": "oznacza zadanie jako zrobione",
        "benefit": "widzi, co już skończył",
        "acceptance": ["zrobione zadanie jest oznaczone na liście"],
    },
]

INTERVIEW = [
    _say(
        message=(
            "Cześć! Pomogę Ci opisać aplikację, a potem ją zbudujemy. Na początek: czy "
            "aplikacja będzie przechowywać dane osobowe, np. imiona albo adresy e-mail?"
        )
    ),
    _say(
        message="Dziękuję. Na jakich urządzeniach będziesz z niej korzystać?",
        updates={"personal_data": "nie"},
    ),
    _say(message="Świetnie, zasady projektu gotowe.", updates={"devices": "komputer i telefon"}),
    _say(message="Teraz opowiedz, co ma robić Twoja aplikacja i kto będzie z niej korzystać."),
    _say(
        message="Mam wszystko, czego potrzebuję. Sprawdź podsumowanie.",
        updates={
            "name": "Lista zadań",
            "goal": "porządek w codziennych sprawach",
            "users": "ja i moja rodzina",
        },
        stories=STORIES,
        assumptions=["Lista jest jedna dla wszystkich domowników"],
    ),
    _say(message=f"Jeszcze jedno pytanie: {QUESTION}"),
    _say(message="Dziękuję, to wszystko.", clarifications={QUESTION: "nie, tytuł jest wymagany"}),
]

CONSTITUTION = """# Lista zadań Constitution

## Core Principles

### I. Test-First
Każda funkcja ma testy z kryteriów akceptacji, zanim powstanie kod.

### II. Simplicity
Najprostsze rozwiązanie, które spełnia wymagania.

### III. Clear Errors
Błędy są opisane prostym językiem.

## Governance
Version: 1.0.0
"""

_SPEC = """# Feature Specification: Lista zadań

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dodawanie zadań (Priority: P1)

Użytkownik dodaje zadanie z tytułem, żeby pamiętać, co ma zrobić.

**Acceptance Scenarios**:

1. **Given** pusta lista, **When** użytkownik doda zadanie, **Then** zadanie jest na liście.
2. **Given** dowolna lista, **When** tytuł jest pusty, **Then** zadanie nie zostaje dodane.

---

### User Story 2 - Oznaczanie jako zrobione (Priority: P2)

Użytkownik oznacza zadanie jako zrobione, żeby widzieć, co już skończył.

**Acceptance Scenarios**:

1. **Given** zadanie na liście, **When** użytkownik je oznaczy, **Then** jest zrobione.

## Requirements *(mandatory)*

- **FR-001**: System MUST odrzucać zadania z pustym tytułem{marker}.
"""
SPEC_WITH_QUESTION = _SPEC.format(marker=f" [NEEDS CLARIFICATION: {QUESTION}]")
SPEC = _SPEC.format(marker="")

PLAN = """# Implementation Plan: Lista zadań

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI, Jinja2
**Storage**: SQLite
**Testing**: pytest
"""

TASKS = """## Phase 1: Setup
- [ ] T001 Create todo list module in app/todos.py

## Phase 2: User Story 1 - Dodawanie zadań (Priority: P1)

### Tests for User Story 1
- [ ] T002 [US1] Test adding todos in tests/test_add.py

### Implementation for User Story 1
- [ ] T003 [US1] Implement adding todos in app/todos.py

## Phase 3: User Story 2 - Oznaczanie jako zrobione (Priority: P2)

### Tests for User Story 2
- [ ] T004 [US2] Test completing todos in tests/test_complete.py

### Implementation for User Story 2
- [ ] T005 [US2] Implement completing todos in app/todos.py
"""

_STUB = """class TodoList:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def add(self, title: str) -> None:
        raise NotImplementedError

    def complete(self, index: int) -> None:
        raise NotImplementedError
"""

_ADD = """    def add(self, title: str) -> None:
        if not title.strip():
            raise ValueError("Tytuł zadania jest wymagany.")
        self.items.append({"title": title.strip(), "done": False})
"""

_COMPLETE = """    def complete(self, index: int) -> None:
        self.items[index]["done"] = True
"""

TEST_ADD = """import pytest

from app.todos import TodoList


def test_added_todo_is_on_the_list():
    todos = TodoList()
    todos.add("Kupić mleko")
    assert todos.items == [{"title": "Kupić mleko", "done": False}]


def test_empty_title_is_rejected():
    with pytest.raises(ValueError):
        TodoList().add("  ")
"""

TEST_COMPLETE = """from app.todos import TodoList


def test_completed_todo_is_marked():
    todos = TodoList()
    todos.add("Kupić mleko")
    todos.complete(0)
    assert todos.items[0]["done"] is True
"""

_STUB_ADD_DONE = _STUB.replace(
    """    def add(self, title: str) -> None:
        raise NotImplementedError
""",
    _ADD,
)
_ALL_DONE = _STUB_ADD_DONE.replace(
    """    def complete(self, index: int) -> None:
        raise NotImplementedError
""",
    _COMPLETE,
)

WORKSPACE_FILES = {
    "pyproject.toml": (
        '[project]\nname = "lista-zadan"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n\n'
        '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n'
    ),
}
"""Szkielet projektu dla demo (konfiguracja pytest jest plikiem chronionym)."""


def _planner() -> dict[str, Scenario | list[Scenario]]:
    return {
        "/speckit.constitution": Scenario(
            name="constitution", files={".specify/memory/constitution.md": CONSTITUTION}
        ),
        "/speckit.specify": Scenario(
            name="specify",
            files={
                f"{FEATURE}/spec.md": SPEC_WITH_QUESTION,
                ".specify/feature.json": json.dumps({"feature_directory": FEATURE}),
            },
        ),
        f"Update {FEATURE}/spec.md": Scenario(name="clarify", files={f"{FEATURE}/spec.md": SPEC}),
        "/speckit.plan": Scenario(name="plan", files={f"{FEATURE}/plan.md": PLAN}),
        "/speckit.tasks": Scenario(name="tasks", files={f"{FEATURE}/tasks.md": TASKS}),
        "/speckit.analyze": Scenario(name="analyze", final_text="Brak problemów krytycznych."),
        "Zadanie T001": success({"app/__init__.py": "", "app/todos.py": _STUB}),
        "Zadanie T002": success({"tests/test_add.py": TEST_ADD}, notes="Testy w tests/test_add.py"),
        "Zadanie T003": success({"app/todos.py": _STUB_ADD_DONE}),
        "Zadanie T004": success({"tests/test_complete.py": TEST_COMPLETE}),
        "Zadanie T005": success({"app/todos.py": _ALL_DONE}),
    }


class DemoHarness(MockHarness):
    """Mock z nagranym demo. Wywiad ma osobny przebieg dla każdej sesji (projektu)."""

    name = "mock"

    def __init__(self, *, step_delay_s: float = 0.0) -> None:
        super().__init__(by_match=_planner(), step_delay_s=step_delay_s)
        self._interviews: dict[str, Iterator[Scenario]] = {}

    def _pick(self, prompt: Prompt, session: Session) -> Scenario:
        if isinstance(prompt, TextPrompt) and MARKER in prompt.text:
            turns = self._interviews.setdefault(
                session.id, itertools.chain(INTERVIEW, itertools.repeat(INTERVIEW[-1]))
            )
            return next(turns)
        return super()._pick(prompt, session)


def prepare_workspace(workspace: Workspace) -> None:
    """Szkielet projektu demo (zamiast `specify init`, którego lokalnie nie ma)."""
    for relative, content in WORKSPACE_FILES.items():
        target = workspace.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    workspace.commit("chore: szkielet projektu (demo)")
