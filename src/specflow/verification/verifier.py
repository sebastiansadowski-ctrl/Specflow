"""Weryfikacja zadania: jedyny "sędzia", który może przenieść zadanie do Done (ADR-0001).

Kontrole nie ufają agentowi - zakładamy, że może (przez błąd albo "sprytnie") próbować
przejść weryfikację bez działającego kodu (reward hacking). Dlatego:
- zmiany bierzemy z gita, nie z deklaracji agenta,
- testy uruchamiamy sami, w środowisku agenta, bez udziału modelu (ADR-0006),
- pilnujemy plików chronionych, liczby testów i regresji.
"""

import shutil
from fnmatch import fnmatch
from pathlib import Path

from pydantic import BaseModel, Field

from specflow.harness import Harness, RunFinished
from specflow.harness.permissions import TEST_PATHS
from specflow.verification.junit import JUnitReport, ids_in_files, parse_junit
from specflow.workspace import Workspace

JUNIT_PATH = ".specflow/junit.xml"
PROTECTED_CONFIG = ["conftest.py", "**/conftest.py", "pytest.ini", "tox.ini", "setup.cfg"]
PYTEST_CONFIG_MARKERS = ("[tool.pytest", "addopts", "testpaths", "python_files")
TEST_WRITER_ALLOWED = ["pyproject.toml", "uv.lock", "requirements*.txt"]


# PYTHONDONTWRITEBYTECODE: plik .py zmieniony w tej samej sekundzie na treść o tej samej
# długości (np. "a - b" -> "a + b") może zostać wczytany ze STAREGO .pyc - weryfikacja
# oceniałaby poprzednią wersję kodu. Bez cache bajtkodu zawsze testujemy bieżące pliki.
NO_BYTECODE = "PYTHONDONTWRITEBYTECODE=1"


class VerificationPolicy(BaseModel):
    max_attempts: int = 3
    test_command: str = (
        f"{NO_BYTECODE} uv run pytest -q -p no:cacheprovider --junitxml={JUNIT_PATH}"
    )
    test_timeout_s: float = 600
    feedback_limit: int = 4000


class TaskUnderTest(BaseModel):
    """To, co weryfikacja musi wiedzieć o zadaniu (bez zależności od tabel bazy)."""

    key: str
    title: str
    is_test: bool
    files: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class VerificationResult(BaseModel):
    ok: bool
    checks: list[CheckResult]
    feedback: str = ""
    """Przycięta informacja zwrotna dla agenta (Rework)."""
    protected_violation: bool = False
    """Wykonawca zmienił testy lub ich konfigurację - zmiany trzeba cofnąć."""
    tests_ran: bool = False
    passing: set[str] = Field(default_factory=set)
    known: set[str] = Field(default_factory=set)

    def summary(self) -> str:
        failed = [c for c in self.checks if not c.ok]
        if not failed:
            return "Wszystkie kontrole przeszły."
        return "; ".join(f"{c.name}: {c.detail}" for c in failed)


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, p) or fnmatch(Path(path).name, p) for p in patterns)


def _is_test_file(path: str) -> bool:
    return _matches(path, TEST_PATHS)


class Verifier:
    def __init__(self, harness: Harness, policy: VerificationPolicy | None = None) -> None:
        self.harness = harness
        self.policy = policy or VerificationPolicy()

    async def verify(
        self,
        task: TaskUnderTest,
        run: RunFinished,
        workspace: Workspace,
        *,
        base_sha: str | None,
        baseline_passing: set[str],
        baseline_known: set[str],
        checkpoint_files: list[str] | None = None,
    ) -> VerificationResult:
        """`checkpoint_files`: pliki testów historyjki, gdy to jej ostatnie zadanie -
        wtedy WSZYSTKIE testy historyjki muszą przejść (Checkpoint ze Spec Kit)."""
        checks: list[CheckResult] = []
        failing_messages: list[str] = []
        output_tail = ""

        # 1. Agent skończył normalnie i oddał poprawny raport "done".
        if run.status != "completed":
            checks.append(CheckResult(name="agent", ok=False, detail=run.error or run.status))
        elif run.report is None:
            checks.append(
                CheckResult(name="raport", ok=False, detail=run.report_error or "brak raportu")
            )
        else:
            checks.append(CheckResult(name="agent", ok=True))

        # 2. Zmiany z gita (nie z deklaracji agenta).
        changed = workspace.changed_files(base_sha)
        if task.files and not changed:
            checks.append(
                CheckResult(
                    name="zmiany", ok=False, detail="agent zgłosił wykonanie, ale nic nie zmienił"
                )
            )
        else:
            checks.append(CheckResult(name="zmiany", ok=True, detail=f"{len(changed)} plików"))

        # 3. Pliki chronione.
        violation = False
        if task.is_test:
            outside = [
                f for f in changed if not _is_test_file(f) and not _matches(f, TEST_WRITER_ALLOWED)
            ]
            if outside:
                checks.append(
                    CheckResult(
                        name="zakres",
                        ok=False,
                        detail=f"zadanie testowe zmieniło kod aplikacji: {', '.join(outside)}",
                    )
                )
        else:
            touched = [f for f in changed if _is_test_file(f) or _matches(f, PROTECTED_CONFIG)]
            if "pyproject.toml" in changed and self._pytest_config_changed(workspace, base_sha):
                touched.append("pyproject.toml [tool.pytest]")
            if touched:
                violation = True
                checks.append(
                    CheckResult(
                        name="pliki chronione",
                        ok=False,
                        detail=f"zmieniono testy lub ich konfigurację: {', '.join(touched)}",
                    )
                )

        # 4. Testy uruchamiane przez nas, w środowisku agenta.
        report: JUnitReport | None = None
        has_tests = any(_is_test_file(f) for f in workspace.files())
        if violation:
            pass  # testy po zmianie testów nic nie dowodzą
        elif not has_tests:
            checks.append(
                CheckResult(name="testy", ok=True, detail="projekt nie ma jeszcze testów")
            )
        else:
            report, output_tail, test_checks = await self._run_tests(workspace)
            checks.extend(test_checks)
            if report is not None:
                checks.extend(
                    self._judge_tests(
                        task, report, baseline_passing, baseline_known, checkpoint_files
                    )
                )
                failing_messages = [
                    f"{case.id}: {case.message}" if case.message else case.id
                    for case in report.cases.values()
                    if case.status == "failed"
                ]

        ok = all(c.ok for c in checks)
        result = VerificationResult(
            ok=ok,
            checks=checks,
            protected_violation=violation,
            tests_ran=report is not None,
            passing=report.passed if report else set(baseline_passing),
            known=report.ids if report else set(baseline_known),
        )
        if not ok:
            result.feedback = self._feedback(task, checks, failing_messages, output_tail)
        return result

    async def _run_tests(
        self, workspace: Workspace
    ) -> tuple[JUnitReport | None, str, list[CheckResult]]:
        junit = workspace.path / JUNIT_PATH
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.unlink(missing_ok=True)  # agent nie może podsunąć starego wyniku
        for stale in workspace.path.rglob("__pycache__"):
            if ".venv" not in stale.parts:
                shutil.rmtree(stale, ignore_errors=True)
        result = await self.harness.run_command(
            workspace.path, self.policy.test_command, timeout_s=self.policy.test_timeout_s
        )
        tail = result.output[-1500:]
        if result.timed_out:
            return (
                None,
                tail,
                [CheckResult(name="testy", ok=False, detail="przekroczono limit czasu")],
            )
        if result.exit_code == 5:
            return JUnitReport(), tail, [CheckResult(name="testy", ok=True, detail="brak testów")]
        if result.exit_code not in (0, 1) or not junit.exists():
            return (
                None,
                tail,
                [
                    CheckResult(
                        name="zbieranie testów",
                        ok=False,
                        detail=f"pytest nie uruchomił testów (kod {result.exit_code})",
                    )
                ],
            )
        return parse_junit(junit.read_text()), tail, []

    def _judge_tests(
        self,
        task: TaskUnderTest,
        report: JUnitReport,
        baseline_passing: set[str],
        baseline_known: set[str],
        checkpoint_files: list[str] | None,
    ) -> list[CheckResult]:
        checks: list[CheckResult] = []

        disappeared = sorted(baseline_known - report.ids)
        checks.append(
            CheckResult(
                name="liczba testów",
                ok=not disappeared,
                detail=f"zniknęły testy: {', '.join(disappeared[:5])}" if disappeared else "",
            )
        )

        regressions = sorted(baseline_passing & report.failed)
        checks.append(
            CheckResult(
                name="regresje",
                ok=not regressions,
                detail=f"przestały przechodzić: {', '.join(regressions[:5])}"
                if regressions
                else "",
            )
        )

        if task.is_test:
            new = report.ids - baseline_known
            if not new:
                checks.append(CheckResult(name="TDD", ok=False, detail="nie dodano nowych testów"))
            elif new <= report.passed:
                checks.append(
                    CheckResult(
                        name="TDD",
                        ok=False,
                        detail="nowe testy przechodzą bez implementacji (niczego nie sprawdzają)",
                    )
                )
            else:
                checks.append(CheckResult(name="TDD", ok=True, detail=f"{len(new)} nowych testów"))

        if checkpoint_files:
            story_tests = ids_in_files(report.ids, checkpoint_files)
            failing = sorted(story_tests - report.passed)
            checks.append(
                CheckResult(
                    name="checkpoint historyjki",
                    ok=bool(story_tests) and not failing,
                    detail=(
                        f"nie przechodzą: {', '.join(failing[:5])}"
                        if failing
                        else ("brak testów historyjki" if not story_tests else "")
                    ),
                )
            )
        return checks

    @staticmethod
    def _pytest_config_changed(workspace: Workspace, base_sha: str | None) -> bool:
        diff = workspace.diff(base_sha, "pyproject.toml")
        changed_lines = [
            line
            for line in diff.splitlines()
            if line[:1] in "+-" and line[:3] not in ("+++", "---")
        ]
        return any(marker in line for line in changed_lines for marker in PYTEST_CONFIG_MARKERS)

    def _feedback(
        self,
        task: TaskUnderTest,
        checks: list[CheckResult],
        failing: list[str],
        output_tail: str,
    ) -> str:
        lines = [f"Weryfikacja zadania {task.key} nie przeszła:"]
        lines += [f"- {c.name}: {c.detail}" for c in checks if not c.ok]
        if failing:
            lines.append("Nieprzechodzące testy:")
            lines += [f"  * {message}" for message in failing[:10]]
        if output_tail:
            lines += ["Końcówka wyjścia testów:", output_tail.strip()]
        text = "\n".join(lines)
        return text[: self.policy.feedback_limit]
