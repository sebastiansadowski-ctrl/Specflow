import asyncio
from pathlib import Path

from conftest import (
    CONSTITUTION_OK,
    FEATURE,
    FEATURE_JSON,
    MARKER_Q,
    PLAN_OK,
    SPEC_OK,
    TASKS_OK,
    writes,
)
from specflow.domain.project_phase import (
    InvalidPhaseTransitionError,
    ProjectPhase,
    advance_phase,
)
from specflow.harness import TextPrompt
from specflow.harness.mock import MockHarness, Scenario
from specflow.planning import (
    PlanningPipeline,
    check_constitution,
    check_plan,
    check_spec,
    clarification_markers,
    critical_findings,
    story_titles,
)
from specflow.workspace import Workspace

FIXTURES = Path(__file__).parent / "fixtures"
SPEC_WITH_MARKER = SPEC_OK.format(marker=f" [NEEDS CLARIFICATION: {MARKER_Q}]")
SPEC_CLEAN = SPEC_OK.format(marker=" (e-mail i hasło)")


# --- kontrole artefaktów ------------------------------------------------------------


def test_raw_templates_are_rejected() -> None:
    constitution = check_constitution((FIXTURES / "speckit_constitution_template.md").read_text())
    assert not constitution.ok and "[PRINCIPLE_1_DESCRIPTION]" in constitution.problems[0]
    spec_template = (FIXTURES / "speckit_spec_template.md").read_text()
    spec = check_spec(spec_template, expected_stories=3)
    assert not spec.ok and any("Brief Title" in p for p in spec.problems)
    assert len(clarification_markers(spec_template)) == 2


def test_good_artifacts_pass() -> None:
    assert check_constitution(CONSTITUTION_OK).ok
    assert check_spec(SPEC_CLEAN, expected_stories=2).ok
    assert story_titles(SPEC_CLEAN) == ["Logowanie", "Dodawanie zadań"]
    assert check_plan(PLAN_OK).ok


def test_spec_with_missing_story_or_scenarios_is_rejected() -> None:
    result = check_spec(SPEC_CLEAN, expected_stories=3)
    assert result.problems == ["specyfikacja ma 2 historyjek, a wywiad zebrał 3"]
    no_given = SPEC_CLEAN.replace("**Given** zalogowany", "Zalogowany")
    assert check_spec(no_given, 2).problems == [
        "historyjka 2 nie ma scenariuszy akceptacji (**Given** …)"
    ]


def test_plan_must_use_fixed_stack() -> None:
    result = check_plan(PLAN_OK.replace("pytest", "unittest"))
    assert result.problems == ["plan nie używa ustalonego stosu: brak 'pytest'"]


def test_critical_findings_from_analyze_table() -> None:
    report = """| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| A1 | Duplication | HIGH | spec.md:L10 | Dwa podobne wymagania | Połącz |
| C1 | Constitution | CRITICAL | tasks.md | Brak testów dla US2 | Dodaj testy |
"""
    [finding] = critical_findings(report)
    assert "Brak testów dla US2" in finding


def test_project_phases() -> None:
    assert advance_phase(ProjectPhase.SPECIFY, ProjectPhase.CLARIFY) is ProjectPhase.CLARIFY
    assert advance_phase(ProjectPhase.REVIEW, ProjectPhase.SPECIFY) is ProjectPhase.SPECIFY
    try:
        advance_phase(ProjectPhase.CONSTITUTION, ProjectPhase.BUILDING)
    except InvalidPhaseTransitionError:
        pass
    else:
        raise AssertionError("pominięcie planowania musi być zabronione")


# --- potok planowania na Mocku ------------------------------------------------------


def run[T](coro_factory) -> T:  # type: ignore[no-untyped-def]
    return asyncio.run(coro_factory())


def test_specify_finds_feature_dir_and_clarification_questions(project_ws: Workspace) -> None:
    harness = MockHarness(
        by_match={
            "/speckit.specify": writes(
                {f"{FEATURE}/spec.md": SPEC_WITH_MARKER, ".specify/feature.json": FEATURE_JSON}
            )
        }
    )
    pipeline = PlanningPipeline(harness, project_ws)
    result = run(lambda: pipeline.specify("brief", expected_stories=2))
    assert result.ok and result.feature_dir == FEATURE
    assert result.open_questions == [MARKER_Q]


def test_clarify_replaces_markers(project_ws: Workspace) -> None:
    (project_ws.path / FEATURE).mkdir(parents=True)
    (project_ws.path / FEATURE / "spec.md").write_text(SPEC_WITH_MARKER)
    harness = MockHarness(by_match={"Update specs/": writes({f"{FEATURE}/spec.md": SPEC_CLEAN})})
    result = run(
        lambda: PlanningPipeline(harness, project_ws).clarify(FEATURE, {MARKER_Q: "e-mail"})
    )
    assert result.ok
    _, prompt = harness.prompts[0]
    assert isinstance(prompt, TextPrompt) and f'"{MARKER_Q}" -> e-mail' in prompt.text


def test_bad_artifact_gets_one_fix_then_blocks(project_ws: Workspace) -> None:
    bad_plan = PLAN_OK.replace("SQLite", "PostgreSQL")
    harness = MockHarness(
        by_match={
            "/speckit.plan": writes({f"{FEATURE}/plan.md": bad_plan}),
            "Fix specs/": writes({f"{FEATURE}/plan.md": bad_plan}),
        }
    )
    result = run(lambda: PlanningPipeline(harness, project_ws).plan(FEATURE))
    assert not result.ok and result.problems == ["plan nie używa ustalonego stosu: brak 'sqlite'"]
    assert [p.name if not isinstance(p, TextPrompt) else "fix" for _, p in harness.prompts] == [
        "speckit.plan",
        "fix",
    ]


def test_tasks_repair_loop_uses_repair_prompt(project_ws: Workspace) -> None:
    broken = TASKS_OK.replace("T003 [US1]", "T003 [US1] (depends on T099)")
    harness = MockHarness(
        by_match={
            "/speckit.tasks": writes({f"{FEATURE}/tasks.md": broken}),
            "Plik tasks.md ma": writes({f"{FEATURE}/tasks.md": TASKS_OK}),
            "/speckit.analyze": Scenario(name="analyze", final_text="Brak problemów krytycznych."),
        }
    )
    result = run(lambda: PlanningPipeline(harness, project_ws).tasks(FEATURE))
    assert result.ok and result.graph is not None and len(result.graph.tasks) == 5
    repair = [p.text for _, p in harness.prompts if isinstance(p, TextPrompt)]
    assert len(repair) == 1 and "UNKNOWN_DEPENDENCY" in repair[0]


def test_tasks_block_after_two_repairs(project_ws: Workspace) -> None:
    broken = TASKS_OK.replace("T003 [US1]", "T003 [US1] (depends on T099)")
    harness = MockHarness(
        by_match={
            "/speckit.tasks": writes({f"{FEATURE}/tasks.md": broken}),
            "Plik tasks.md ma": writes({f"{FEATURE}/tasks.md": broken}),
        }
    )
    result = run(lambda: PlanningPipeline(harness, project_ws).tasks(FEATURE))
    assert not result.ok and "UNKNOWN_DEPENDENCY" in result.problems[0]
    repairs = [p for _, p in harness.prompts if isinstance(p, TextPrompt)]
    assert len(repairs) == 2


def test_tests_after_implementation_are_rejected_by_constitution_policy(
    project_ws: Workspace,
) -> None:
    flipped = TASKS_OK.replace(
        "### Tests for User Story 1\n- [ ] T002 [US1] Test logowania w tests/test_login.py\n\n"
        "### Implementation for User Story 1\n- [ ] T003 [US1] Logowanie w app/login.py",
        "### Implementation for User Story 1\n- [ ] T002 [US1] Logowanie w app/login.py\n\n"
        "### Tests for User Story 1\n- [ ] T003 [US1] Test logowania w tests/test_login.py",
    )
    harness = MockHarness(by_match={"/speckit.tasks": writes({f"{FEATURE}/tasks.md": flipped})})
    pipeline = PlanningPipeline(harness, project_ws, max_task_repairs=0)
    result = run(lambda: pipeline.tasks(FEATURE))
    assert not result.ok and "TESTS_AFTER_IMPLEMENTATION" in result.problems[0]


def test_critical_analysis_triggers_one_fix(project_ws: Workspace) -> None:
    table = "| C1 | Constitution | CRITICAL | tasks.md | Brak testów | Dodaj |"
    harness = MockHarness(
        by_match={
            "/speckit.tasks": writes({f"{FEATURE}/tasks.md": TASKS_OK}),
            "/speckit.analyze": Scenario(name="analyze", final_text=table),
            "CRITICAL findings": writes({f"{FEATURE}/tasks.md": TASKS_OK}),
        }
    )
    result = run(lambda: PlanningPipeline(harness, project_ws).tasks(FEATURE))
    assert result.ok and result.warnings == [
        "/speckit.analyze: 1 krytycznych niespójności, poprawiane"
    ]


def test_constitution_stage(project_ws: Workspace) -> None:
    harness = MockHarness(
        by_match={
            "/speckit.constitution": writes({".specify/memory/constitution.md": CONSTITUTION_OK})
        }
    )
    assert run(lambda: PlanningPipeline(harness, project_ws).constitution("brief")).ok
