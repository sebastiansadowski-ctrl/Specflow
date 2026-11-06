"""Przepływ projektu na Mocku: wywiad → bramki → planowanie Spec Kit → kanban."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from conftest import (
    CONSTITUTION_OK,
    FEATURE,
    FEATURE_JSON,
    MARKER_Q,
    PLAN_OK,
    SPEC_OK,
    TASKS_OK,
    say,
    writes,
)
from specflow.domain import TaskStatus
from specflow.domain.project_phase import ProjectPhase as P
from specflow.harness import CommandPrompt, TextPrompt
from specflow.harness.mock import MockHarness, Scenario
from specflow.planning.flow import ProjectFlow
from specflow.storage import ProjectStore, init_db, make_engine, session_factory
from specflow.workspace import Workspace, run_command

STORIES: list[dict[str, Any]] = [
    {
        "title": "Logowanie",
        "actor": "użytkownik",
        "action": "loguje się e-mailem",
        "benefit": "widzi swoje zadania",
        "acceptance": ["po dobrym haśle widzi listę"],
    },
    {
        "title": "Dodawanie zadań",
        "actor": "użytkownik",
        "action": "dodaje zadanie",
        "benefit": "pamięta, co zrobić",
        "acceptance": ["nowe zadanie widać na liście"],
    },
]
SPEC_WITH_MARKER = SPEC_OK.format(marker=f" [NEEDS CLARIFICATION: {MARKER_Q}]")
SPEC_CLEAN = SPEC_OK.format(marker=" (e-mail i hasło)")

INTERVIEW = [
    say(message="Czy aplikacja będzie przechowywać dane osobowe?"),
    say(
        message="Dziękuję!",
        updates={"personal_data": "tak, e-maile i hasła", "devices": "komputer"},
    ),
    say(message="Opowiedz, co ma robić aplikacja."),
    say(
        message="Mam wszystko, co trzeba.",
        updates={"name": "Lista zadań", "goal": "porządek w sprawach", "users": "rodzina"},
        stories=STORIES,
        assumptions=["Logowanie tylko e-mailem i hasłem"],
    ),
    say(message=f"Jedno pytanie: {MARKER_Q}"),
    say(message="Dzięki, to wszystko.", clarifications={MARKER_Q: "e-mail i hasło"}),
]


def planner(tasks: Scenario | list[Scenario] | None = None) -> dict[str, Scenario | list[Scenario]]:
    return {
        "/speckit.constitution": writes({".specify/memory/constitution.md": CONSTITUTION_OK}),
        "/speckit.specify": writes(
            {f"{FEATURE}/spec.md": SPEC_WITH_MARKER, ".specify/feature.json": FEATURE_JSON}
        ),
        "Update specs/": writes({f"{FEATURE}/spec.md": SPEC_CLEAN}),
        "/speckit.plan": writes({f"{FEATURE}/plan.md": PLAN_OK}),
        "/speckit.tasks": tasks or writes({f"{FEATURE}/tasks.md": TASKS_OK}),
        "/speckit.analyze": Scenario(name="analyze", final_text="Brak problemów krytycznych."),
    }


@pytest.fixture
def store() -> Iterator[ProjectStore]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as s:
        yield ProjectStore(s)


def make_flow(
    store: ProjectStore, ws: Workspace, interview: list[Scenario], **planner_overrides: Any
) -> tuple[ProjectFlow, MockHarness, int]:
    project = store.create_project("Lista zadań")
    harness = MockHarness(by_match={"[wywiad]": list(interview), **planner(**planner_overrides)})
    return ProjectFlow(store, harness, ws, project.id), harness, project.id


def go(coro: Any) -> Any:
    return asyncio.run(coro)


def test_full_flow_from_interview_to_kanban(store: ProjectStore, project_ws: Workspace) -> None:
    flow, harness, pid = make_flow(store, project_ws, INTERVIEW)

    first = go(flow.start())
    assert first.phase is P.CONSTITUTION and "dane osobowe" in first.message
    assert first.progress == (0, 2)

    after_rules = go(flow.message("Tak, e-maile i hasła, używam na komputerze"))
    assert after_rules.phase is P.SPECIFY
    assert after_rules.message == "Opowiedz, co ma robić aplikacja."
    assert (project_ws.path / ".specify/memory/constitution.md").exists()

    gate = go(flow.message("Chcę listę zadań dla rodziny, z logowaniem i dodawaniem zadań."))
    assert gate.gate == "spec" and gate.gate_summary is not None
    assert "**Logowanie**" in gate.gate_summary
    assert "sprawdzimy: nowe zadanie widać na liście" in gate.gate_summary
    assert "Logowanie tylko e-mailem i hasłem" in gate.gate_summary  # założenie widoczne

    clarify = go(flow.approve())
    assert clarify.phase is P.CLARIFY and MARKER_Q in clarify.message

    plan_gate = go(flow.message("E-mail i hasło"))
    assert plan_gate.phase is P.REVIEW and plan_gate.gate == "plan"
    assert plan_gate.gate_summary is not None
    assert "Historyjki (2)" in plan_gate.gate_summary and "Python 3.12" in plan_gate.gate_summary
    assert "5 w 3 fazach, w tym 2 zadań z testami" in plan_gate.gate_summary

    building = go(flow.approve())
    assert building.phase is P.BUILDING
    tasks = store.board_tasks(pid)
    assert [t.key for t in tasks] == ["T001", "T002", "T003", "T004", "T005"]
    assert store.get_task(pid, "T001").status == TaskStatus.READY.value
    log = run_command(["git", "log", "--format=%s"], project_ws.path)
    assert "docs: specyfikacja i plan (Spec Kit)" in log

    # Wywiad i planista mają osobne, stałe sesje.
    interview_sessions = {
        sid for sid, p in harness.prompts if isinstance(p, TextPrompt) and "[wywiad]" in p.text
    }
    planner_sessions = {sid for sid, p in harness.prompts if isinstance(p, CommandPrompt)}
    assert len(interview_sessions) == 1 and len(planner_sessions) == 1
    assert interview_sessions != planner_sessions

    roles = [m.role for m in store.messages(pid)]
    assert roles[0] == "assistant" and "user" in roles and "system" in roles


def test_change_request_at_spec_gate_returns_to_interview(
    store: ProjectStore, project_ws: Workspace
) -> None:
    third = {**STORIES[0], "title": "Usuwanie zadań", "acceptance": ["usunięte znika z listy"]}
    interview = [
        *INTERVIEW[:4],
        say(message="Dodałem usuwanie.", stories=[*STORIES, third]),
    ]
    flow, _, _ = make_flow(store, project_ws, interview)
    go(flow.start())
    go(flow.message("dane: tak, komputer"))
    gate = go(flow.message("lista zadań"))
    assert gate.gate == "spec"

    changed = go(flow.message("Dodaj jeszcze usuwanie zadań"))
    assert changed.gate == "spec" and changed.gate_summary is not None
    assert "**Usuwanie zadań**" in changed.gate_summary


def test_blocked_planning_is_retried_with_user_hint(
    store: ProjectStore, project_ws: Workspace
) -> None:
    broken = writes(
        {f"{FEATURE}/tasks.md": TASKS_OK.replace("T003 [US1]", "T003 [US1] (depends on T099)")}
    )
    fixed = writes({f"{FEATURE}/tasks.md": TASKS_OK})
    flow, harness, pid = make_flow(store, project_ws, INTERVIEW, tasks=[broken, fixed])
    harness.by_match["Plik tasks.md ma"] = broken

    go(flow.start())
    go(flow.message("dane"))
    go(flow.message("opis"))
    go(flow.approve())
    blocked = go(flow.message("E-mail i hasło"))
    assert blocked.blocked is not None and "UNKNOWN_DEPENDENCY" in blocked.blocked
    assert store.get_project(pid).phase == P.TASKS.value

    retried = go(flow.message("Usuń zależność od T099"))
    assert retried.blocked is None and retried.gate == "plan"
    guidance = [
        p.text
        for _, p in harness.prompts
        if isinstance(p, TextPrompt) and "User guidance" in p.text
    ]
    assert guidance == ["User guidance for the planning: Usuń zależność od T099"]
