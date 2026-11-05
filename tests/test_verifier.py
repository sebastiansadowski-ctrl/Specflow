import asyncio
import os
from pathlib import Path

from conftest import TEST_POLICY, done_run
from specflow.harness import RunFinished
from specflow.harness.mock import MockHarness
from specflow.verification import TaskUnderTest, VerificationResult, Verifier, ids_in_files
from specflow.verification.junit import parse_junit
from specflow.workspace import Workspace

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.test_calc" name="test_add" time="0.001"/>
  <testcase classname="tests.test_calc.TestSub" name="test_sub" time="0.001">
    <failure message="assert -1 == 1">trace</failure>
  </testcase>
  <testcase classname="tests.test_other" name="test_skip"><skipped message="x"/></testcase>
</testsuite></testsuites>"""

IMPL = TaskUnderTest(key="T003", title="Implement add", is_test=False, files=["calc.py"])
TEST_TASK = TaskUnderTest(key="T002", title="Test add", is_test=True, files=["tests/test_calc.py"])
FAILING_TEST = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def write(ws: Workspace, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = ws.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def verify(
    ws: Workspace,
    task: TaskUnderTest,
    *,
    run: RunFinished | None = None,
    passing: set[str] | None = None,
    known: set[str] | None = None,
    checkpoint: list[str] | None = None,
) -> VerificationResult:
    verifier = Verifier(MockHarness(), TEST_POLICY)
    return asyncio.run(
        verifier.verify(
            task,
            run or done_run(),
            ws,
            base_sha=ws.head(),
            baseline_passing=passing or set(),
            baseline_known=known or set(),
            checkpoint_files=checkpoint,
        )
    )


def failed(result: VerificationResult) -> set[str]:
    return {c.name for c in result.checks if not c.ok}


def test_parse_junit_and_map_ids_to_files() -> None:
    report = parse_junit(JUNIT)
    assert report.passed == {"tests.test_calc::test_add"}
    assert report.failed == {"tests.test_calc.TestSub::test_sub"}
    assert report.cases["tests.test_calc.TestSub::test_sub"].message == "assert -1 == 1"
    assert ids_in_files(report.ids, ["tests/test_calc.py"]) == {
        "tests.test_calc::test_add",
        "tests.test_calc.TestSub::test_sub",
    }


def test_phantom_done_is_rejected(project_ws: Workspace) -> None:
    result = verify(project_ws, IMPL)
    assert not result.ok and failed(result) == {"zmiany"}
    assert "nic nie zmienił" in result.feedback


def test_missing_report_is_rejected(project_ws: Workspace) -> None:
    write(project_ws, {"calc.py": "def add(a, b):\n    return a + b\n"})
    run = RunFinished(status="completed", report=None, report_error="brak raportu")
    assert failed(verify(project_ws, IMPL, run=run)) == {"raport"}


def test_timeout_is_rejected(project_ws: Workspace) -> None:
    write(project_ws, {"calc.py": "x = 1\n"})
    run = RunFinished(status="timeout", error="limit")
    assert failed(verify(project_ws, IMPL, run=run)) == {"agent"}


def test_project_without_tests_passes_test_step(project_ws: Workspace) -> None:
    write(project_ws, {"calc.py": "def add(a, b):\n    return a + b\n"})
    result = verify(project_ws, IMPL)
    assert result.ok and not result.tests_ran


def test_implementer_editing_tests_is_a_protected_violation(project_ws: Workspace) -> None:
    write(project_ws, {"tests/test_calc.py": FAILING_TEST})
    project_ws.commit("tests")
    write(project_ws, {"calc.py": "x = 1\n", "tests/test_calc.py": "def test_add():\n    pass\n"})
    result = verify(project_ws, IMPL)
    assert result.protected_violation
    assert failed(result) == {"pliki chronione"}


def test_pytest_config_change_in_pyproject_is_protected(project_ws: Workspace) -> None:
    write(
        project_ws,
        {
            "calc.py": "x = 1\n",
            "pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["."]\naddopts = "-k nic"\n',
        },
    )
    assert verify(project_ws, IMPL).protected_violation


def test_tdd_new_failing_test_is_accepted(project_ws: Workspace) -> None:
    write(project_ws, {"calc.py": "def add(a, b):\n    raise NotImplementedError\n"})
    project_ws.commit("stub")
    write(project_ws, {"tests/test_calc.py": FAILING_TEST})
    result = verify(project_ws, TEST_TASK)
    assert result.ok, result.feedback
    assert result.known == {"tests.test_calc::test_add"} and not result.passing


def test_tdd_test_passing_without_implementation_is_rejected(project_ws: Workspace) -> None:
    write(project_ws, {"tests/test_calc.py": "def test_trivial():\n    assert True\n"})
    assert failed(verify(project_ws, TEST_TASK)) == {"TDD"}


def test_test_writer_may_not_touch_app_code(project_ws: Workspace) -> None:
    write(
        project_ws,
        {
            "calc.py": "def add(a, b):\n    raise NotImplementedError\n",
            "tests/test_calc.py": FAILING_TEST,
        },
    )
    assert "zakres" in failed(verify(project_ws, TEST_TASK))


def test_collection_error_is_rejected(project_ws: Workspace) -> None:
    write(project_ws, {"tests/test_calc.py": "def broken(:\n"})
    assert "zbieranie testów" in failed(verify(project_ws, TEST_TASK))


def test_regression_and_disappeared_tests_are_rejected(project_ws: Workspace) -> None:
    write(
        project_ws,
        {
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": FAILING_TEST,
        },
    )
    project_ws.commit("works")
    write(project_ws, {"calc.py": "def add(a, b):\n    return a - b\n"})
    result = verify(
        project_ws,
        IMPL,
        passing={"tests.test_calc::test_add"},
        known={"tests.test_calc::test_add", "tests.test_gone::test_x"},
    )
    assert failed(result) == {"regresje", "liczba testów"}
    assert "tests.test_calc::test_add" in result.feedback


def test_story_checkpoint_requires_all_story_tests_green(project_ws: Workspace) -> None:
    write(
        project_ws,
        {
            "calc.py": "def add(a, b):\n    raise NotImplementedError\n",
            "tests/test_calc.py": FAILING_TEST,
        },
    )
    project_ws.commit("red")
    known = {"tests.test_calc::test_add"}

    write(project_ws, {"calc.py": "def add(a, b):\n    return 0\n"})
    still_red = verify(project_ws, IMPL, known=known, checkpoint=["tests/test_calc.py"])
    assert failed(still_red) == {"checkpoint historyjki"}
    # Bez checkpointu (nie ostatnie zadanie historyjki) to samo jest dopuszczalne.
    assert verify(project_ws, IMPL, known=known).ok

    write(project_ws, {"calc.py": "def add(a, b):\n    return a + b\n"})
    green = verify(project_ws, IMPL, known=known, checkpoint=["tests/test_calc.py"])
    assert green.ok and green.passing == known


def test_feedback_is_trimmed(project_ws: Workspace) -> None:
    write(project_ws, {"tests/test_calc.py": "def broken(:\n" + "#" * 10_000})
    result = verify(project_ws, TEST_TASK)
    assert len(result.feedback) <= TEST_POLICY.feedback_limit


def test_stale_junit_file_cannot_fake_results(project_ws: Workspace, tmp_path: Path) -> None:
    write(project_ws, {"tests/test_calc.py": "def broken(:\n"})
    write(project_ws, {".specflow/junit.xml": JUNIT})  # "podrzucony" wynik
    assert "zbieranie testów" in failed(verify(project_ws, TEST_TASK))


def test_same_size_edit_is_not_hidden_by_stale_bytecode(project_ws: Workspace) -> None:
    """Regresja z CI: "a - b" -> "a + b" w tej samej sekundzie (ten sam rozmiar pliku)."""
    write(
        project_ws,
        {"calc.py": "def add(a, b):\n    return a - b\n", "tests/test_calc.py": FAILING_TEST},
    )
    project_ws.commit("red")
    known = {"tests.test_calc::test_add"}
    assert not verify(project_ws, IMPL, known=known, checkpoint=["tests/test_calc.py"]).ok
    calc = project_ws.path / "calc.py"
    stat = calc.stat()
    write(project_ws, {"calc.py": "def add(a, b):\n    return a + b\n"})
    os.utime(calc, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # ta sama sekunda i rozmiar
    assert verify(project_ws, IMPL, known=known, checkpoint=["tests/test_calc.py"]).ok
