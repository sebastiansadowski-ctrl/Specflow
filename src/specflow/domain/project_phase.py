"""Etapy projektu: druga maszyna stanów, na poziomie całego projektu (ADR-0007).

constitution → specify → clarify → plan → tasks → review → building → done
Wywiad i planowanie przesuwają projekt do przodu; bramki akceptacji (specyfikacja, plan)
wymagają decyzji użytkownika. Z bramki planu można wrócić do doprecyzowania specyfikacji.
"""

from enum import StrEnum


class ProjectPhase(StrEnum):
    CONSTITUTION = "constitution"
    """Wywiad o zasadach projektu (1-2 pytania, reszta to domyślne zasady Specflow)."""
    SPECIFY = "specify"
    """Wywiad o tym, CO ma powstać; kończy się bramką akceptacji specyfikacji."""
    CLARIFY = "clarify"
    """Pytania ze znaczników [NEEDS CLARIFICATION] w spec.md."""
    PLAN = "plan"
    """/speckit.plan (stos ustalony przez Specflow)."""
    TASKS = "tasks"
    """/speckit.tasks + walidacja + /speckit.analyze."""
    REVIEW = "review"
    """Bramka akceptacji planu."""
    BUILDING = "building"
    """Zadania w kanbanie, pracuje orkiestrator."""
    DONE = "done"


P = ProjectPhase

PHASE_TRANSITIONS: dict[ProjectPhase, frozenset[ProjectPhase]] = {
    P.CONSTITUTION: frozenset({P.SPECIFY}),
    P.SPECIFY: frozenset({P.CLARIFY, P.PLAN}),
    P.CLARIFY: frozenset({P.PLAN}),
    P.PLAN: frozenset({P.TASKS}),
    P.TASKS: frozenset({P.REVIEW}),
    P.REVIEW: frozenset({P.BUILDING, P.SPECIFY}),
    P.BUILDING: frozenset({P.DONE}),
    P.DONE: frozenset(),
}

PHASE_LABELS: dict[ProjectPhase, str] = {
    P.CONSTITUTION: "Zasady",
    P.SPECIFY: "Specyfikacja",
    P.CLARIFY: "Doprecyzowanie",
    P.PLAN: "Plan",
    P.TASKS: "Zadania",
    P.REVIEW: "Akceptacja planu",
    P.BUILDING: "Realizacja",
    P.DONE: "Gotowe",
}


class InvalidPhaseTransitionError(Exception):
    pass


def advance_phase(current: ProjectPhase, target: ProjectPhase) -> ProjectPhase:
    if target not in PHASE_TRANSITIONS[current]:
        raise InvalidPhaseTransitionError(f"{current.value} -> {target.value}: niedozwolone")
    return target
