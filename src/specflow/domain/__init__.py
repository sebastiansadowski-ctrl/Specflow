"""Model domeny.

Czysty, deterministyczny kod bez wywołań LLM: parser `tasks.md`, walidacja wyjścia
modelu, graf zależności (DAG) i maszyna stanów zadań. Źródło prawdy dla kanbanu.
"""

from specflow.domain.dag import TaskGraph, build_graph
from specflow.domain.issues import Issue, IssueCode, Severity, ValidationReport
from specflow.domain.plan import PhaseKind, PhaseSpec, TaskPlan, TaskSpec
from specflow.domain.planning import PlanPolicy, PlanResult, load_task_plan
from specflow.domain.state_machine import (
    KANBAN_COLUMNS,
    Actor,
    InvalidTransitionError,
    TaskStatus,
    can_transition,
    transition,
)
from specflow.domain.tasks_parser import parse_tasks_md

__all__ = [
    "KANBAN_COLUMNS",
    "Actor",
    "InvalidTransitionError",
    "Issue",
    "IssueCode",
    "PhaseKind",
    "PhaseSpec",
    "PlanPolicy",
    "PlanResult",
    "Severity",
    "TaskGraph",
    "TaskPlan",
    "TaskSpec",
    "TaskStatus",
    "ValidationReport",
    "build_graph",
    "can_transition",
    "load_task_plan",
    "parse_tasks_md",
    "transition",
]
