from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from specflow.domain import Actor, InvalidTransitionError, TaskGraph, TaskStatus, load_task_plan
from specflow.storage import ProjectStore, ProjectStoreError, init_db, make_engine, session_factory

FIXTURES = Path(__file__).parent / "fixtures"
S = TaskStatus


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as s:
        yield s


@pytest.fixture
def graph() -> TaskGraph:
    result = load_task_plan((FIXTURES / "todo_tasks.md").read_text())
    assert result.graph is not None
    return result.graph


def complete(store: ProjectStore, project_id: int, key: str) -> None:
    store.set_status(project_id, key, S.IN_PROGRESS, Actor.ORCHESTRATOR)
    store.set_status(project_id, key, S.VERIFICATION, Actor.ORCHESTRATOR)
    store.set_status(project_id, key, S.DONE, Actor.VERIFICATION)


def test_import_puts_only_unblocked_tasks_in_ready(session: Session, graph: TaskGraph) -> None:
    store = ProjectStore(session)
    project = store.create_project("Todo demo")
    store.import_plan(project.id, graph)

    board = store.board(project.id)
    assert [t.key for t in board[S.READY]] == ["T001"]
    assert len(board[S.BACKLOG]) == 16
    assert store.next_ready(project.id) is not None


def test_done_task_promotes_dependents(session: Session, graph: TaskGraph) -> None:
    store = ProjectStore(session)
    project = store.create_project("Todo demo")
    store.import_plan(project.id, graph)

    complete(store, project.id, "T001")
    ready = [t.key for t in store.board(project.id)[S.READY]]
    assert ready == ["T002", "T003"]
    next_task = store.next_ready(project.id)
    assert next_task is not None and next_task.key == "T002"


def test_invalid_transition_is_rejected_and_not_logged(session: Session, graph: TaskGraph) -> None:
    store = ProjectStore(session)
    project = store.create_project("Todo demo")
    store.import_plan(project.id, graph)
    events_before = len(store.events(project.id))

    with pytest.raises(InvalidTransitionError):
        store.set_status(project.id, "T001", S.DONE, Actor.USER)

    assert store.get_task(project.id, "T001").status == S.READY.value
    assert len(store.events(project.id)) == events_before


def test_every_status_change_is_an_event(session: Session, graph: TaskGraph) -> None:
    store = ProjectStore(session)
    project = store.create_project("Todo demo")
    store.import_plan(project.id, graph)
    store.set_status(project.id, "T001", S.IN_PROGRESS, Actor.ORCHESTRATOR)
    store.set_status(project.id, "T001", S.VERIFICATION, Actor.ORCHESTRATOR)
    store.set_status(project.id, "T001", S.REWORK, Actor.VERIFICATION, reason="testy nie przeszły")

    changes = [
        (e.task_key, e.from_status, e.to_status, e.actor)
        for e in store.events(project.id)
        if e.type == "status_changed"
    ]
    assert changes == [
        ("T001", "backlog", "ready", "system"),
        ("T001", "ready", "in_progress", "orchestrator"),
        ("T001", "in_progress", "verification", "orchestrator"),
        ("T001", "verification", "rework", "verification"),
    ]
    assert store.events(project.id)[-1].payload == {"reason": "testy nie przeszły"}


def test_rework_counts_attempts(session: Session, graph: TaskGraph) -> None:
    store = ProjectStore(session)
    project = store.create_project("Todo demo")
    store.import_plan(project.id, graph)
    store.set_status(project.id, "T001", S.IN_PROGRESS, Actor.ORCHESTRATOR)
    store.set_status(project.id, "T001", S.VERIFICATION, Actor.ORCHESTRATOR)
    store.set_status(project.id, "T001", S.REWORK, Actor.VERIFICATION)
    store.set_status(project.id, "T001", S.IN_PROGRESS, Actor.ORCHESTRATOR)
    # Każde wejście do In progress to podejście: pierwsze + po Rework.
    assert store.get_task(project.id, "T001").attempts == 2


def test_plan_cannot_be_imported_twice(session: Session, graph: TaskGraph) -> None:
    store = ProjectStore(session)
    project = store.create_project("Todo demo")
    store.import_plan(project.id, graph)
    with pytest.raises(ProjectStoreError):
        store.import_plan(project.id, graph)
