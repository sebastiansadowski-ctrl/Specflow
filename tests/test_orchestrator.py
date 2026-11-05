"""Pełny przepływ orkiestratora na Mocku: prawdziwy git i pytest, baza w pamięci."""

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from conftest import FAILING_TEST_SRC, TEST_POLICY
from specflow.domain import TaskStatus, load_task_plan
from specflow.harness import HarnessError, SessionSpec, TextPrompt
from specflow.harness import Session as AgentSession
from specflow.harness.mock import (
    MockHarness,
    Scenario,
    asks_question,
    broken_code,
    edits_tests,
    phantom_done,
    success,
)
from specflow.orchestrator import Orchestrator, OrchestratorConfig
from specflow.storage import ProjectStore, init_db, make_engine, session_factory
from specflow.workspace import Workspace

PLAN = """## Phase 1: Setup
- [ ] T001 Create calculator stub in calc.py

## Phase 2: User Story 1 - Add numbers (Priority: P1)

### Tests for User Story 1
- [ ] T002 [US1] Test add in tests/test_calc.py

### Implementation for User Story 1
- [ ] T003 [US1] Implement add in calc.py
"""

STUB = {"calc.py": "def add(a, b):\n    raise NotImplementedError\n"}
TESTS = {"tests/test_calc.py": FAILING_TEST_SRC}
IMPL = {"calc.py": "def add(a, b):\n    return a + b\n"}
S = TaskStatus


@pytest.fixture
def db() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as s:
        yield s


def make(
    db: Session, ws: Workspace, t003: Scenario | list[Scenario], harness: MockHarness | None = None
) -> tuple[Orchestrator, ProjectStore, MockHarness, int]:
    store = ProjectStore(db)
    project = store.create_project("calc")
    result = load_task_plan(PLAN)
    assert result.graph is not None
    store.import_plan(project.id, result.graph)
    harness = harness or MockHarness(
        by_match={"T001": success(STUB), "T002": success(TESTS), "T003": t003}
    )
    orch = Orchestrator(
        store,
        harness,
        ws,
        project.id,
        policy=TEST_POLICY,
        config=OrchestratorConfig(retry_delays_s=[0.0]),
    )
    return orch, store, harness, project.id


def run(orch: Orchestrator) -> list[str]:
    return [o.outcome for o in asyncio.run(orch.run_until_idle())]


def git_log(ws: Workspace) -> list[str]:
    from specflow.workspace import run_command

    return run_command(["git", "log", "--format=%s"], ws.path).splitlines()


def test_happy_path_tdd_red_then_green(db: Session, project_ws: Workspace) -> None:
    orch, store, _, pid = make(db, project_ws, success(IMPL, notes="add() zwraca sumę"))
    assert run(orch) == ["done", "done", "done"]
    assert all(t.status == S.DONE.value for t in store.board_tasks(pid))
    assert git_log(project_ws)[:3] == [
        "T003: Implement add in calc.py",
        "T002: Test add in tests/test_calc.py",
        "T001: Create calculator stub in calc.py",
    ]
    project = store.get_project(pid)
    assert project.passing_tests == ["tests.test_calc::test_add"]
    assert store.get_task(pid, "T003").notes == "add() zwraca sumę"
    assert [r.outcome for r in store.runs(pid)] == ["done", "done", "done"]


def test_phantom_done_exhausts_attempts_then_hint_starts_fresh_session(
    db: Session, project_ws: Workspace
) -> None:
    t003 = [phantom_done(), phantom_done(), phantom_done(), success(IMPL)]
    orch, store, harness, pid = make(db, project_ws, t003)
    assert run(orch) == ["done", "done", "awaiting_input"]

    task = store.get_task(pid, "T003")
    assert task.status == S.AWAITING_INPUT.value
    assert task.awaiting_reason == "attempts_exhausted" and task.attempts == 3
    assert task.awaiting_message is not None and "3 podejścia" in task.awaiting_message
    assert [r.outcome for r in store.runs(pid, "T003")] == ["rework", "rework", "awaiting_input"]
    old_sessions = {sid for sid, _ in harness.prompts[-3:]}
    assert len(old_sessions) == 1  # Rework w tej samej sesji

    orch.answer("T003", "Zaimplementuj add w calc.py")
    task = store.get_task(pid, "T003")
    assert task.status == S.READY.value and task.attempts == 0 and task.session_id is None

    assert run(orch) == ["done"]
    session_id, prompt = harness.prompts[-1]
    assert session_id not in old_sessions  # wskazówka = nowa sesja
    assert isinstance(prompt, TextPrompt)
    assert "Wskazówka od użytkownika (ważna): Zaimplementuj add" in prompt.text
    assert "nic nie zmienił" in prompt.text  # historia porażek
    assert [d.kind for d in store.decisions(pid)] == ["hint"]


def test_editing_tests_is_reverted_and_reworked(db: Session, project_ws: Workspace) -> None:
    cheat = edits_tests("tests/test_calc.py", "def test_add():\n    assert True\n")
    orch, store, _, pid = make(db, project_ws, [cheat, success(IMPL)])
    assert run(orch) == ["done", "done", "done"]
    assert (project_ws.path / "tests/test_calc.py").read_text() == FAILING_TEST_SRC
    first, second = store.runs(pid, "T003")
    assert first.outcome == "rework" and second.outcome == "done"
    assert any(c["name"] == "pliki chronione" and not c["ok"] for c in first.verification["checks"])


def test_question_answer_resumes_same_session(db: Session, project_ws: Workspace) -> None:
    orch, store, harness, pid = make(
        db, project_ws, [asks_question("Liczby całkowite?"), success(IMPL)]
    )
    assert run(orch) == ["done", "done", "awaiting_input"]
    task = store.get_task(pid, "T003")
    assert task.awaiting_reason == "question" and task.awaiting_message == "Liczby całkowite?"
    asked_in = harness.prompts[-1][0]

    orch.answer("T003", "Tak, tylko int")
    assert store.get_task(pid, "T003").attempts == 1  # pytanie nie zużywa podejść

    assert run(orch) == ["done"]
    session_id, prompt = harness.prompts[-1]
    assert session_id == asked_in
    assert isinstance(prompt, TextPrompt)
    assert (
        'Pytałeś: "Liczby całkowite?"' in prompt.text and "Odpowiedź: Tak, tylko int" in prompt.text
    )
    assert [d.kind for d in store.decisions(pid)] == ["answer"]


def test_broken_code_gets_failing_test_in_feedback(db: Session, project_ws: Workspace) -> None:
    broken = broken_code({"calc.py": "def add(a, b):\n    return a - b\n"})
    orch, _, harness, _ = make(db, project_ws, [broken, success(IMPL)])
    assert run(orch) == ["done", "done", "done"]
    rework_prompts = [
        p.text
        for _, p in harness.prompts
        if isinstance(p, TextPrompt) and "weryfikacja nie przeszła" in p.text
    ]
    assert len(rework_prompts) == 1
    assert "checkpoint historyjki" in rework_prompts[0]
    assert "tests.test_calc::test_add" in rework_prompts[0]


def test_failed_attempt_is_saved_on_branch_and_workspace_reset(
    db: Session, project_ws: Workspace
) -> None:
    bad = broken_code({"calc.py": "def add(a, b):\n    return 0\n"})
    orch, store, _, pid = make(db, project_ws, [bad, bad, bad])
    assert run(orch) == ["done", "done", "awaiting_input"]
    last = store.runs(pid, "T003")[-1]
    assert last.attempt_branch is not None and last.attempt_branch.startswith("attempt/T003-")
    assert (project_ws.path / "calc.py").read_text() == STUB["calc.py"]  # stan bazowy
    from specflow.workspace import run_command

    branches = run_command(["git", "branch", "--list", "attempt/*"], project_ws.path)
    assert last.attempt_branch in branches


class FlakyHarness(MockHarness):
    """Infrastruktura niedostępna: start sesji zawsze się nie udaje."""

    async def start_session(self, spec: SessionSpec) -> AgentSession:
        raise HarnessError("connection refused")


def test_infrastructure_failure_pauses_project_without_using_attempts(
    db: Session, project_ws: Workspace
) -> None:
    orch, store, _, pid = make(db, project_ws, success(IMPL), harness=FlakyHarness())
    outcomes = asyncio.run(orch.run_until_idle())
    assert [o.outcome for o in outcomes] == ["paused"]
    assert store.get_project(pid).paused_reason is not None
    task = store.get_task(pid, "T001")
    assert task.status == S.READY.value and task.attempts == 0
    assert asyncio.run(orch.run_next()) is None  # wstrzymany projekt nie startuje zadań
