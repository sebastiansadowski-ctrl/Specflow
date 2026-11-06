import pytest

from specflow.domain import (
    KANBAN_COLUMNS,
    Actor,
    InvalidTransitionError,
    TaskStatus,
    can_transition,
    transition,
)

S = TaskStatus


@pytest.mark.parametrize(
    ("current", "target", "actor"),
    [
        (S.BACKLOG, S.READY, Actor.SYSTEM),
        (S.READY, S.IN_PROGRESS, Actor.ORCHESTRATOR),
        (S.IN_PROGRESS, S.VERIFICATION, Actor.ORCHESTRATOR),
        (S.IN_PROGRESS, S.AWAITING_INPUT, Actor.ORCHESTRATOR),
        (S.IN_PROGRESS, S.READY, Actor.ORCHESTRATOR),
        (S.VERIFICATION, S.DONE, Actor.VERIFICATION),
        (S.VERIFICATION, S.REWORK, Actor.VERIFICATION),
        (S.VERIFICATION, S.AWAITING_INPUT, Actor.VERIFICATION),
        (S.REWORK, S.IN_PROGRESS, Actor.ORCHESTRATOR),
        (S.AWAITING_INPUT, S.READY, Actor.USER),
    ],
)
def test_allowed_transitions(current: TaskStatus, target: TaskStatus, actor: Actor) -> None:
    assert transition(current, target, actor) is target


@pytest.mark.parametrize("actor", [Actor.USER, Actor.ORCHESTRATOR, Actor.SYSTEM])
def test_only_verification_can_mark_done(actor: Actor) -> None:
    with pytest.raises(InvalidTransitionError, match="tylko: verification"):
        transition(S.VERIFICATION, S.DONE, actor)


@pytest.mark.parametrize("actor", list(Actor))
def test_nobody_can_skip_verification(actor: Actor) -> None:
    assert not can_transition(S.IN_PROGRESS, S.DONE, actor)
    assert not can_transition(S.READY, S.DONE, actor)


def test_unknown_transition_has_clear_message() -> None:
    with pytest.raises(InvalidTransitionError, match="takie przejście nie istnieje"):
        transition(S.DONE, S.BACKLOG, Actor.USER)


def test_kanban_columns_cover_every_status_once() -> None:
    statuses = [status for status, _ in KANBAN_COLUMNS]
    assert sorted(statuses) == sorted(TaskStatus)
