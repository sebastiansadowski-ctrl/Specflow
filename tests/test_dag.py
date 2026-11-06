from pathlib import Path

from specflow.domain import IssueCode, PlanPolicy, TaskGraph, load_task_plan

FIXTURES = Path(__file__).parent / "fixtures"


def graph_for(text: str) -> TaskGraph:
    result = load_task_plan(text)
    assert result.graph is not None, result.report.as_repair_prompt()
    return result.graph


def test_phase_rules_stories_do_not_depend_on_each_other() -> None:
    graph = graph_for((FIXTURES / "todo_tasks.md").read_text())
    foundational = {"T001", "T002", "T003", "T004", "T005", "T006"}
    us1 = {"T007", "T008", "T009", "T010", "T011"}
    # US2 czeka na fazy przygotowawcze, ale nie na US1.
    assert foundational <= graph.deps["T012"]
    assert not (us1 & graph.deps["T012"])
    # Polish czeka na wszystko.
    assert foundational | us1 <= graph.deps["T016"]


def test_barrier_rules_inside_phase() -> None:
    graph = graph_for((FIXTURES / "todo_tasks.md").read_text())
    # [P] po barierze T001 czeka tylko na barierę.
    assert graph.deps["T002"] == {"T001"}
    assert graph.deps["T003"] == {"T001"}
    # Zadanie bez [P] czeka na wszystkie wcześniejsze w fazie.
    assert {"T001", "T002", "T003"} <= graph.deps["T004"]
    # Podsekcja "### Implementation" jest barierą: kod czeka na testy.
    assert {"T007", "T008"} <= graph.deps["T009"]
    # Testy [P] w tej samej podsekcji nie czekają na siebie.
    assert "T007" not in graph.deps["T008"]


def test_execution_order_respects_priority_and_dependencies() -> None:
    graph = graph_for((FIXTURES / "todo_tasks.md").read_text())
    order = graph.execution_order()
    assert order == [f"T{n:03d}" for n in range(1, 18)]
    position = {t: i for i, t in enumerate(order)}
    for task_id, deps in graph.deps.items():
        assert all(position[d] < position[task_id] for d in deps)


def test_unknown_and_self_dependencies_are_errors() -> None:
    text = """## Phase 1: Setup
- [ ] T001 Create a in src/a.py (depends on T099)
- [ ] T002 Create b in src/b.py (depends on T002)
"""
    result = load_task_plan(text)
    assert result.graph is None
    assert [i.code for i in result.report.errors] == [
        IssueCode.UNKNOWN_DEPENDENCY,
        IssueCode.SELF_DEPENDENCY,
    ]


def test_cycle_is_detected_with_readable_path() -> None:
    text = """## Phase 1: Setup
- [ ] T001 [P] Create a in src/a.py (depends on T002)
- [ ] T002 [P] Create b in src/b.py (depends on T001)
"""
    result = load_task_plan(text)
    assert result.graph is None
    [cycle] = result.report.errors
    assert cycle.code is IssueCode.CYCLE
    assert "T001" in cycle.message and "T002" in cycle.message


def test_parallel_tasks_touching_same_file_are_serialized() -> None:
    text = """## Phase 1: Setup
- [ ] T001 [P] Add model in src/models.py
- [ ] T002 [P] Add another model in src/models.py
"""
    result = load_task_plan(text)
    assert result.graph is not None
    assert result.graph.deps["T002"] == {"T001"}
    assert [i.code for i in result.report.warnings] == [IssueCode.FILE_CONFLICT]


def test_duplicate_ids_are_errors() -> None:
    text = "## Phase 1: Setup\n- [ ] T001 A in src/a.py\n- [ ] T001 B in src/b.py\n"
    result = load_task_plan(text)
    assert [i.code for i in result.report.errors] == [IssueCode.DUPLICATE_TASK_ID]


def test_empty_input_is_an_error() -> None:
    result = load_task_plan("# Tasks\n\nNothing here.\n")
    assert [i.code for i in result.report.errors] == [IssueCode.NO_TASKS]


def test_tests_first_policy() -> None:
    text = """## Phase 1: User Story 1 - Login (Priority: P1)
- [ ] T001 [US1] Implement login in src/login.py
- [ ] T002 [US1] Contract test for login in tests/test_login.py
"""
    assert load_task_plan(text).ok
    strict = load_task_plan(text, PlanPolicy(require_tests_first=True))
    assert not strict.ok
    [issue] = strict.report.errors
    assert issue.code is IssueCode.TESTS_AFTER_IMPLEMENTATION
    assert issue.task_id == "T002"


def test_repair_prompt_lists_numbered_errors_for_the_model() -> None:
    result = load_task_plan((FIXTURES / "speckit_tasks_template.md").read_text())
    prompt = result.report.as_repair_prompt()
    assert prompt.startswith("Plik tasks.md ma ")
    assert "1. [ERROR] PLACEHOLDER" in prompt
    assert "zachowaj format Spec Kit" in prompt
    assert load_task_plan((FIXTURES / "todo_tasks.md").read_text()).report.as_repair_prompt() == ""


def test_direct_deps_remove_transitive_edges_but_keep_readiness() -> None:
    graph = graph_for((FIXTURES / "todo_tasks.md").read_text())
    direct = graph.direct_deps()
    assert direct["T002"] == {"T001"}
    # T010 zależy od wszystkiego z faz przygotowawczych i od testów US1, ale bezpośrednio
    # tylko od T009 (jawne depends on), które samo czeka na resztę.
    assert direct["T010"] == {"T009"}
    # Gotowość się nie zmienia: domknięcie przechodnie bezpośrednich = pełne zależności.
    for task_id, deps in graph.deps.items():
        closure: set[str] = set()
        stack = list(direct[task_id])
        while stack:
            dep = stack.pop()
            if dep not in closure:
                closure.add(dep)
                stack.extend(direct[dep])
        assert closure == deps
