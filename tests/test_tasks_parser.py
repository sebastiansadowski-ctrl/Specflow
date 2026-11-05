from pathlib import Path

from specflow.domain import Issue, IssueCode, PhaseKind, Severity, parse_tasks_md

FIXTURES = Path(__file__).parent / "fixtures"


def codes(report_issues: list[Issue]) -> list[IssueCode]:
    return [issue.code for issue in report_issues]


def test_parses_phases_with_kinds_stories_and_priorities() -> None:
    plan, _ = parse_tasks_md((FIXTURES / "todo_tasks.md").read_text())
    kinds = [(p.kind, p.story, p.priority) for p in plan.phases]
    assert kinds == [
        (PhaseKind.SETUP, None, None),
        (PhaseKind.FOUNDATIONAL, None, None),
        (PhaseKind.STORY, "US1", 1),
        (PhaseKind.STORY, "US2", 2),
        (PhaseKind.POLISH, None, None),
    ]


def test_parses_task_markers_files_deps_and_test_flag() -> None:
    plan, report = parse_tasks_md((FIXTURES / "todo_tasks.md").read_text())
    tasks = {t.id: t for t in plan.tasks}
    assert len(tasks) == 17
    assert tasks["T007"].parallel and tasks["T007"].story == "US1" and tasks["T007"].is_test
    assert tasks["T010"].explicit_deps == ["T009"]
    assert tasks["T010"].files == ["src/todo/services/auth.py"]
    assert tasks["T002"].files == ["pyproject.toml"]
    assert not tasks["T011"].is_test
    assert tasks["T009"].section_index == 2  # "### Implementation" po "### Tests"
    assert report.ok


def test_ignores_html_comments_code_fences_and_non_phase_sections() -> None:
    text = """
## Phase 1: Setup
<!--
- [ ] T900 sample task inside a comment
-->
```
- [ ] T901 sample task inside a code fence
```
- [ ] T001 Create structure in src/app.py

## Notes
- [ ] T002 Stray task outside any phase in src/x.py
"""
    plan, report = parse_tasks_md(text)
    assert [t.id for t in plan.tasks] == ["T001"]
    assert codes(report.issues) == [IssueCode.TASK_OUTSIDE_PHASE]


def test_checked_box_is_only_a_warning_never_a_status() -> None:
    plan, report = parse_tasks_md("## Phase 1: Setup\n- [X] T001 Done already in src/a.py\n")
    assert plan.tasks[0].prechecked
    assert codes(report.warnings) == [IssueCode.PRECHECKED_TASK]
    assert report.ok


def test_rejects_invalid_ids_and_placeholders() -> None:
    text = """## Phase 1: Setup
- [ ] TXXX Documentation updates in docs/a.md
- [ ] 12 Missing T prefix in src/a.py
- [ ] T003 Create [Entity] model in src/models/[entity].py
"""
    _, report = parse_tasks_md(text)
    assert codes(report.errors) == [
        IssueCode.PLACEHOLDER,
        IssueCode.INVALID_TASK_ID,
        IssueCode.PLACEHOLDER,
    ]


def test_original_speckit_template_is_rejected_as_unfinished_output() -> None:
    _, report = parse_tasks_md((FIXTURES / "speckit_tasks_template.md").read_text())
    assert not report.ok
    error_codes = set(codes(report.errors))
    assert error_codes == {IssueCode.PLACEHOLDER}
    # Placeholder w nagłówku "Phase N", w tytułach historyjek i w opisach zadań.
    assert any("Phase N" in i.message for i in report.errors)
    assert all(i.severity is Severity.ERROR for i in report.errors)
