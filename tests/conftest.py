import sys
from pathlib import Path

import pytest

from specflow.harness import AgentReport, RunFinished
from specflow.verification import JUNIT_PATH, VerificationPolicy
from specflow.verification.verifier import NO_BYTECODE
from specflow.workspace import Workspace

# Testy projektu generowanego przez "agenta" uruchamiamy tym samym interpreterem co nasze testy.
TEST_POLICY = VerificationPolicy(
    test_command=(
        f"{NO_BYTECODE} {sys.executable} -m pytest -q -p no:cacheprovider --junitxml={JUNIT_PATH}"
    ),
    test_timeout_s=120,
)


FAILING_TEST_SRC = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def done_run() -> RunFinished:
    return RunFinished(status="completed", report=AgentReport(status="done", summary="ok"))


@pytest.fixture
def project_ws(tmp_path: Path) -> Workspace:
    """Workspace projektu z konfiguracją pytest w commicie bazowym."""
    ws = Workspace.create(tmp_path, 1, "calc")
    (ws.path / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    ws.commit("base")
    return ws


# --- wspólne dla testów wywiadu i planowania (M4) ---------------------------------
import json  # noqa: E402
from typing import Any  # noqa: E402

from specflow.harness.mock import Scenario  # noqa: E402


def say(**payload: Any) -> Scenario:
    """Scenariusz Mocka: model odpowiada blokiem JSON (tura wywiadu)."""
    body = json.dumps(payload, ensure_ascii=False)
    return Scenario(name="say", final_text=f"```json\n{body}\n```")


def writes(files: dict[str, str], text: str = "Gotowe.") -> Scenario:
    """Scenariusz Mocka: planista zapisuje pliki (komenda Spec Kit)."""
    return Scenario(name="writes", files=files, final_text=text)


CONSTITUTION_OK = """# Todo Constitution

## Core Principles

### I. Test-First
Każda funkcja ma testy z kryteriów akceptacji, zanim powstanie kod.

### II. Simplicity
Najprostsze rozwiązanie.

## Governance
Version: 1.0.0
"""

SPEC_OK = """# Feature Specification: Lista zadań

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Logowanie (Priority: P1)

Użytkownik loguje się e-mailem i hasłem.

**Acceptance Scenarios**:

1. **Given** zarejestrowany użytkownik, **When** poda dobre hasło, **Then** widzi swoją listę.

---

### User Story 2 - Dodawanie zadań (Priority: P2)

Użytkownik dodaje zadanie.

**Acceptance Scenarios**:

1. **Given** zalogowany użytkownik, **When** doda zadanie, **Then** widzi je na liście.

## Requirements *(mandatory)*

- **FR-001**: System MUST pozwalać na logowanie{marker}.
"""

PLAN_OK = """# Implementation Plan: Lista zadań

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI, Jinja2
**Storage**: SQLite
**Testing**: pytest
"""

TASKS_OK = """## Phase 1: Setup
- [ ] T001 Create project structure in app/__init__.py

## Phase 2: User Story 1 - Logowanie (Priority: P1)

### Tests for User Story 1
- [ ] T002 [US1] Test logowania w tests/test_login.py

### Implementation for User Story 1
- [ ] T003 [US1] Logowanie w app/login.py

## Phase 3: User Story 2 - Dodawanie zadań (Priority: P2)

### Tests for User Story 2
- [ ] T004 [US2] Test dodawania w tests/test_todos.py

### Implementation for User Story 2
- [ ] T005 [US2] Dodawanie zadań w app/todos.py
"""

FEATURE = "specs/001-lista-zadan"
FEATURE_JSON = json.dumps({"feature_directory": FEATURE})
MARKER_Q = "metoda logowania: e-mail i hasło czy Google?"
