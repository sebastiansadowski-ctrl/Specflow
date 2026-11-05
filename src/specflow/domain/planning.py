"""Punkt wejścia: tekst `tasks.md` od modelu -> zwalidowany graf zadań.

Warstwy: [1] parser -> [2] schemat (identyfikatory, placeholdery) -> [3] graf
(zależności, cykle, konflikty plików) -> [4] polityki projektu (np. testy przed kodem).
Jeśli są błędy, `PlanResult.graph` jest None, a `report.as_repair_prompt()` daje listę
uwag dla planisty. Po wyczerpaniu prób naprawy plan trafia do Awaiting input (ADR-0004).
"""

from pydantic import BaseModel

from specflow.domain.dag import TaskGraph, build_graph
from specflow.domain.issues import IssueCode, Severity, ValidationReport
from specflow.domain.plan import PhaseKind, TaskPlan
from specflow.domain.tasks_parser import parse_tasks_md


class PlanPolicy(BaseModel):
    require_tests_first: bool = False
    """W fazach historyjek zadania testowe muszą stać przed implementacją (TDD)."""


class PlanResult(BaseModel):
    plan: TaskPlan
    graph: TaskGraph | None
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.graph is not None


def _check_policies(plan: TaskPlan, policy: PlanPolicy) -> ValidationReport:
    report = ValidationReport()
    if not policy.require_tests_first:
        return report
    for phase in plan.phases:
        if phase.kind is not PhaseKind.STORY:
            continue
        implementation_seen: str | None = None
        for task in (t for t in plan.tasks if t.phase_index == phase.index):
            if not task.is_test:
                implementation_seen = implementation_seen or task.id
            elif implementation_seen:
                report.add(
                    IssueCode.TESTS_AFTER_IMPLEMENTATION,
                    Severity.ERROR,
                    f"Konstytucja wymaga testów przed implementacją, a test stoi po "
                    f"zadaniu {implementation_seen}. Przenieś go przed implementację.",
                    task_id=task.id,
                    line=task.line,
                )
    return report


def load_task_plan(text: str, policy: PlanPolicy | None = None) -> PlanResult:
    policy = policy or PlanPolicy()
    plan, report = parse_tasks_md(text)

    if not plan.tasks:
        report.add(
            IssueCode.NO_TASKS,
            Severity.ERROR,
            "Nie znaleziono żadnych zadań w formacie `- [ ] T001 opis` w sekcjach "
            "`## Phase N: ...`.",
        )
        return PlanResult(plan=plan, graph=None, report=report)

    graph, graph_report = build_graph(plan)
    report.extend(graph_report)
    report.extend(_check_policies(plan, policy))

    return PlanResult(plan=plan, graph=graph if report.ok else None, report=report)
