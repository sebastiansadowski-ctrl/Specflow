"""Maszyna stanów zadań z kontrolą, KTO może wykonać przejście.

Element bezpieczeństwa: ani agent, ani użytkownik nie przeniesie zadania do Done.
Done ustawia wyłącznie weryfikacja, na podstawie dowodu (ADR-0001).
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    VERIFICATION = "verification"
    AWAITING_INPUT = "awaiting_input"
    REWORK = "rework"
    DONE = "done"


class Actor(StrEnum):
    SYSTEM = "system"
    """Automatyczne reguły, np. Backlog -> Ready po ukończeniu zależności."""
    ORCHESTRATOR = "orchestrator"
    VERIFICATION = "verification"
    USER = "user"


S = TaskStatus

TRANSITIONS: dict[tuple[TaskStatus, TaskStatus], frozenset[Actor]] = {
    (S.BACKLOG, S.READY): frozenset({Actor.SYSTEM}),
    (S.READY, S.IN_PROGRESS): frozenset({Actor.ORCHESTRATOR}),
    (S.IN_PROGRESS, S.VERIFICATION): frozenset({Actor.ORCHESTRATOR}),
    # Agent może sam zgłosić pytanie / brak informacji w trakcie pracy.
    (S.IN_PROGRESS, S.AWAITING_INPUT): frozenset({Actor.ORCHESTRATOR}),
    # Awaria infrastruktury (agent niedostępny): zadanie wraca do kolejki, bez oceny pracy.
    (S.IN_PROGRESS, S.READY): frozenset({Actor.ORCHESTRATOR}),
    (S.VERIFICATION, S.DONE): frozenset({Actor.VERIFICATION}),
    (S.VERIFICATION, S.REWORK): frozenset({Actor.VERIFICATION}),
    (S.VERIFICATION, S.AWAITING_INPUT): frozenset({Actor.VERIFICATION}),
    (S.REWORK, S.IN_PROGRESS): frozenset({Actor.ORCHESTRATOR}),
    (S.AWAITING_INPUT, S.READY): frozenset({Actor.USER}),
}

KANBAN_COLUMNS: list[tuple[TaskStatus, str]] = [
    (S.BACKLOG, "Backlog"),
    (S.READY, "Ready"),
    (S.IN_PROGRESS, "In progress"),
    (S.VERIFICATION, "Verification"),
    (S.AWAITING_INPUT, "Awaiting input"),
    (S.REWORK, "Rework"),
    (S.DONE, "Done"),
]


class InvalidTransitionError(Exception):
    def __init__(self, current: TaskStatus, target: TaskStatus, actor: Actor) -> None:
        allowed = TRANSITIONS.get((current, target))
        if allowed is None:
            reason = "takie przejście nie istnieje"
        else:
            names = ", ".join(sorted(a.value for a in allowed))
            reason = f"może je wykonać tylko: {names}"
        super().__init__(f"{current.value} -> {target.value} przez {actor.value}: {reason}")
        self.current = current
        self.target = target
        self.actor = actor


def can_transition(current: TaskStatus, target: TaskStatus, actor: Actor) -> bool:
    return actor in TRANSITIONS.get((current, target), frozenset())


def transition(current: TaskStatus, target: TaskStatus, actor: Actor) -> TaskStatus:
    if not can_transition(current, target, actor):
        raise InvalidTransitionError(current, target, actor)
    return target
