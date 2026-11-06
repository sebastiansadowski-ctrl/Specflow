"""Budowa i walidacja grafu zależności zadań (DAG) - wariant ostrożny.

Reguły (ADR-0004):
1. Fazy: Setup -> Foundational -> każda historyjka osobno -> Polish. Historyjki nie
   zależą od siebie nawzajem (zgodnie z szablonem Spec Kit). Faza "other" i Polish
   czekają na wszystkie wcześniejsze fazy.
2. W fazie: zadanie bez [P] jest barierą i czeka na wszystkie wcześniejsze zadania fazy;
   zadanie [P] czeka tylko na ostatnią barierę. Podsekcja `###` też jest barierą
   (np. "Implementation" czeka na "Tests").
3. Jawne `(depends on T012)` dodają krawędzie.
4. Dwa zadania, które mogłyby iść równolegle, a dotykają tego samego pliku,
   dostają krawędź według kolejności w pliku (ostrzeżenie FILE_CONFLICT).

Zależność to nie kolejność: graf mówi, co MUSI być wcześniej. Priorytety (P1 przed P2)
to osobna reguła harmonogramu - patrz `TaskGraph.execution_order()`.
"""

import heapq
from collections import defaultdict

from pydantic import BaseModel, Field

from specflow.domain.issues import IssueCode, Severity, ValidationReport
from specflow.domain.plan import PhaseKind, TaskPlan, TaskSpec


class TaskGraph(BaseModel):
    tasks: dict[str, TaskSpec] = Field(default_factory=dict)
    deps: dict[str, set[str]] = Field(default_factory=dict)
    """task_id -> zbiór zadań, które muszą być ukończone wcześniej."""
    file_order: list[str] = Field(default_factory=list)
    phase_rank: dict[int, int] = Field(default_factory=dict)
    """phase_index -> pozycja w harmonogramie (historyjki według priorytetu)."""

    def direct_deps(self) -> dict[str, set[str]]:
        """Redukcja przechodnia: tylko BEZPOŚREDNIE zależności (A→C usuwamy, gdy A→B→C).
        Gotowość zadań się nie zmienia, a notatki przekazania w promptach pochodzą
        tylko od zadań, na których praca faktycznie się opiera."""
        ancestors = {task_id: _ancestors(task_id, self.deps) for task_id in self.deps}
        return {
            task_id: {
                dep
                for dep in deps
                if not any(dep in ancestors[other] for other in deps if other != dep)
            }
            for task_id, deps in self.deps.items()
        }

    def execution_order(self) -> list[str]:
        """Topologiczny porządek: z gotowych zadań najpierw faza o niższej randze,
        potem kolejność w pliku. Zakłada brak cykli (sprawdzone przy budowie)."""
        position = {task_id: n for n, task_id in enumerate(self.file_order)}

        def key(task_id: str) -> tuple[int, int]:
            phase = self.tasks[task_id].phase_index
            rank = self.phase_rank.get(phase, 0) if phase is not None else 0
            return (rank, position[task_id])

        remaining = {t: set(d) for t, d in self.deps.items()}
        dependents: dict[str, set[str]] = defaultdict(set)
        for task_id, task_deps in remaining.items():
            for dep in task_deps:
                dependents[dep].add(task_id)

        heap = [(key(t), t) for t, d in remaining.items() if not d]
        heapq.heapify(heap)
        order: list[str] = []
        while heap:
            _, task_id = heapq.heappop(heap)
            order.append(task_id)
            for nxt in dependents[task_id]:
                remaining[nxt].discard(task_id)
                if not remaining[nxt]:
                    heapq.heappush(heap, (key(nxt), nxt))
        return order


def _phase_rank(plan: TaskPlan) -> dict[int, int]:
    """Setup/Foundational w kolejności pliku, potem historyjki według priorytetu,
    na końcu Polish. To tylko harmonogram, nie zależności."""

    def sort_key(index: int) -> tuple[int, int, int]:
        phase = plan.phase(index)
        group = {
            PhaseKind.SETUP: 0,
            PhaseKind.FOUNDATIONAL: 1,
            PhaseKind.STORY: 2,
            PhaseKind.OTHER: 2,
            PhaseKind.POLISH: 3,
        }[phase.kind]
        priority = phase.priority if phase.priority is not None else 99
        return (group, priority if phase.kind is PhaseKind.STORY else 0, index)

    ordered = sorted(range(len(plan.phases)), key=sort_key)
    return {phase_index: rank for rank, phase_index in enumerate(ordered)}


def _required_phases(plan: TaskPlan, index: int) -> list[int]:
    kind = plan.phase(index).kind
    earlier = range(index)
    if kind is PhaseKind.STORY:
        # Historyjki zależą od faz przygotowawczych, ale nie od innych historyjek.
        return [i for i in earlier if plan.phase(i).kind is not PhaseKind.STORY]
    if kind is PhaseKind.SETUP:
        return [i for i in earlier if plan.phase(i).kind is PhaseKind.SETUP]
    # Foundational, Polish, Other: ostrożnie - wszystkie wcześniejsze fazy.
    return list(earlier)


def _ancestors(task_id: str, deps: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(deps.get(task_id, ()))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(deps.get(current, ()))
    return seen


def _find_cycle(deps: dict[str, set[str]], order: list[str]) -> list[str]:
    """Zwraca jeden cykl (lista zadań) albo pustą listę."""
    white, gray, black = 0, 1, 2
    color = dict.fromkeys(deps, white)
    parent: dict[str, str] = {}

    def visit(node: str) -> list[str]:
        color[node] = gray
        for dep in sorted(deps.get(node, ())):
            if color.get(dep, black) == gray:
                cycle = [dep, node]
                current = node
                while current != dep:
                    current = parent[current]
                    cycle.append(current)
                return list(reversed(cycle[:-1]))
            if color.get(dep) == white:
                parent[dep] = node
                found = visit(dep)
                if found:
                    return found
        color[node] = black
        return []

    for node in order:
        if color[node] == white:
            found = visit(node)
            if found:
                return found
    return []


def build_graph(plan: TaskPlan) -> tuple[TaskGraph, ValidationReport]:
    report = ValidationReport()
    graph = TaskGraph(phase_rank=_phase_rank(plan))

    # Unikalność identyfikatorów
    for task in plan.tasks:
        if task.id in graph.tasks:
            report.add(
                IssueCode.DUPLICATE_TASK_ID,
                Severity.ERROR,
                f"Identyfikator {task.id} występuje więcej niż raz "
                f"(pierwszy raz w linii {graph.tasks[task.id].line}).",
                task_id=task.id,
                line=task.line,
            )
            continue
        graph.tasks[task.id] = task
        graph.file_order.append(task.id)
        graph.deps[task.id] = set()

    by_phase: dict[int, list[TaskSpec]] = defaultdict(list)
    for task_id in graph.file_order:
        task = graph.tasks[task_id]
        if task.phase_index is not None:
            by_phase[task.phase_index].append(task)

    for phase in plan.phases:
        if not by_phase.get(phase.index):
            report.add(
                IssueCode.EMPTY_PHASE,
                Severity.WARNING,
                f"Faza '{phase.title}' nie ma żadnych zadań.",
                line=phase.line,
            )

    # Reguła 1: fazy
    for phase_index, phase_tasks in by_phase.items():
        required = [t.id for p in _required_phases(plan, phase_index) for t in by_phase.get(p, [])]
        for task in phase_tasks:
            graph.deps[task.id].update(required)

    # Reguła 2: bariery w fazie
    for phase_tasks in by_phase.values():
        previous: list[str] = []
        barrier: set[str] = set()
        current_section = 0
        for task in phase_tasks:
            if task.section_index != current_section:
                barrier = set(previous)
                current_section = task.section_index
            if task.parallel:
                graph.deps[task.id].update(barrier)
            else:
                graph.deps[task.id].update(previous)
                barrier = {*previous, task.id}
            previous.append(task.id)

    # Reguła 3: jawne zależności
    for task_id in graph.file_order:
        task = graph.tasks[task_id]
        for dep in task.explicit_deps:
            if dep == task_id:
                report.add(
                    IssueCode.SELF_DEPENDENCY,
                    Severity.ERROR,
                    "Zadanie zależy od samego siebie.",
                    task_id=task_id,
                    line=task.line,
                )
            elif dep not in graph.tasks:
                report.add(
                    IssueCode.UNKNOWN_DEPENDENCY,
                    Severity.ERROR,
                    f"Zależność od {dep}, które nie istnieje w planie.",
                    task_id=task_id,
                    line=task.line,
                )
            else:
                graph.deps[task_id].add(dep)

    # Reguła 4: konflikty plików między zadaniami, które mogłyby iść równolegle
    for n, first_id in enumerate(graph.file_order):
        first = graph.tasks[first_id]
        for second_id in graph.file_order[n + 1 :]:
            second = graph.tasks[second_id]
            shared = sorted(set(first.files) & set(second.files))
            if not shared:
                continue
            related = first_id in _ancestors(second_id, graph.deps) or second_id in _ancestors(
                first_id, graph.deps
            )
            if not related:
                graph.deps[second_id].add(first_id)
                report.add(
                    IssueCode.FILE_CONFLICT,
                    Severity.WARNING,
                    f"{first_id} i {second_id} mogłyby iść równolegle, a oba zmieniają "
                    f"{', '.join(shared)}. Dodano zależność {second_id} -> {first_id}.",
                    task_id=second_id,
                    line=second.line,
                )

    cycle = _find_cycle(graph.deps, graph.file_order)
    if cycle:
        path = " -> ".join([*cycle, cycle[0]])
        report.add(
            IssueCode.CYCLE,
            Severity.ERROR,
            f"Cykl zależności: {path}. Usuń jedną z zależności albo zmień kolejność zadań.",
            task_id=cycle[0],
        )

    return graph, report
