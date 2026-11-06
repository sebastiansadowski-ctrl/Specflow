"""Potok planowania: komendy Spec Kit uruchamiane przez agenta-planistę + kontrole kodu.

Wzorzec dla każdego kroku: model (komenda /speckit.*) → kontrola deterministyczna →
przy problemach jedna poprawka w tej samej sesji (dla tasks.md: do 2, z `as_repair_prompt`)
→ jeśli nadal źle: planowanie zablokowane (Awaiting input na poziomie projektu).
"""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from specflow.domain import PlanPolicy, TaskGraph, load_task_plan
from specflow.harness import (
    AgentMessage,
    AgentProfile,
    CommandPrompt,
    Harness,
    HarnessError,
    Prompt,
    RunFinished,
    Session,
    SessionSpec,
    TextPrompt,
)
from specflow.interview.render import (
    render_clarifications_prompt,
    render_plan_brief,
    render_tasks_brief,
)
from specflow.planning.checks import (
    ArtifactCheck,
    check_constitution,
    check_plan,
    check_spec,
    clarification_markers,
    critical_findings,
)
from specflow.workspace import Workspace

CONSTITUTION_PATH = ".specify/memory/constitution.md"


class StageResult(BaseModel):
    ok: bool
    problems: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    """Po /speckit.specify: pytania ze znaczników [NEEDS CLARIFICATION]."""
    feature_dir: str | None = None
    graph: TaskGraph | None = None
    warnings: list[str] = Field(default_factory=list)


class PlanningPipeline:
    def __init__(
        self,
        harness: Harness,
        workspace: Workspace,
        *,
        timeout_s: float = 1800,
        max_task_repairs: int = 2,
        session_id: str | None = None,
    ) -> None:
        self.harness = harness
        self.workspace = workspace
        self.timeout_s = timeout_s
        self.max_task_repairs = max_task_repairs
        self.session_id = session_id
        """Jedna sesja planisty na całe planowanie: plan i zadania widzą, jak powstała spec."""

    # --- sesja ---------------------------------------------------------------------

    def _spec(self) -> SessionSpec:
        return SessionSpec(
            title="Specflow: planowanie", workdir=self.workspace.path, profile=AgentProfile.PLANNER
        )

    async def session(self) -> Session:
        if self.session_id:
            return Session(id=self.session_id, spec=self._spec())
        session = await self.harness.start_session(self._spec())
        self.session_id = session.id
        return session

    async def _run(self, prompt: Prompt) -> str:
        """Uruchamia komendę lub wiadomość w sesji planisty; zwraca ostatni tekst modelu."""
        session = await self.session()
        last_text = ""
        finished: RunFinished | None = None
        async for event in self.harness.run(
            session, prompt, timeout_s=self.timeout_s, expect_report=False
        ):
            if isinstance(event, AgentMessage) and event.text.strip():
                last_text = event.text
            elif isinstance(event, RunFinished):
                finished = event
        if finished is None or finished.status != "completed":
            reason = finished.error or finished.status if finished else "brak zakończenia"
            raise HarnessError(f"Planista nie zakończył pracy: {reason}")
        return last_text

    # --- kroki ---------------------------------------------------------------------

    async def constitution(self, brief: str) -> StageResult:
        await self._run(CommandPrompt(name="speckit.constitution", arguments=brief))
        return await self._checked(CONSTITUTION_PATH, check_constitution)

    async def specify(self, brief: str, expected_stories: int) -> StageResult:
        await self._run(CommandPrompt(name="speckit.specify", arguments=brief))
        feature_dir = self.feature_dir()
        if feature_dir is None:
            return StageResult(ok=False, problems=["/speckit.specify nie utworzył spec.md"])
        result = await self._checked(
            f"{feature_dir}/spec.md", lambda text: check_spec(text, expected_stories)
        )
        result.feature_dir = feature_dir
        if result.ok:
            result.open_questions = clarification_markers(
                self.workspace.read(f"{feature_dir}/spec.md")
            )
        return result

    async def clarify(self, feature_dir: str, clarifications: dict[str, str]) -> StageResult:
        """Nasze doprecyzowanie zamiast /speckit.clarify: odpowiedzi z czatu → planista."""
        await self._run(TextPrompt(text=render_clarifications_prompt(feature_dir, clarifications)))
        remaining = clarification_markers(self.workspace.read(f"{feature_dir}/spec.md"))
        if remaining:
            await self._run(
                TextPrompt(
                    text="Some [NEEDS CLARIFICATION] markers are still in spec.md: "
                    + "; ".join(remaining)
                    + ". Replace them using the answers given above."
                )
            )
            remaining = clarification_markers(self.workspace.read(f"{feature_dir}/spec.md"))
        if remaining:
            return StageResult(
                ok=False, problems=[f"w spec.md zostały znaczniki: {'; '.join(remaining)}"]
            )
        return StageResult(ok=True, feature_dir=feature_dir)

    async def plan(self, feature_dir: str) -> StageResult:
        await self._run(CommandPrompt(name="speckit.plan", arguments=render_plan_brief()))
        result = await self._checked(f"{feature_dir}/plan.md", check_plan)
        result.feature_dir = feature_dir
        return result

    async def tasks(self, feature_dir: str) -> StageResult:
        """/speckit.tasks → walidacja (ADR-0004) → pętla naprawcza → /speckit.analyze."""
        await self._run(CommandPrompt(name="speckit.tasks", arguments=render_tasks_brief()))
        graph, problems = await self._validated_tasks(feature_dir, repairs=self.max_task_repairs)
        if graph is None:
            return StageResult(ok=False, problems=problems, feature_dir=feature_dir)

        warnings: list[str] = []
        analysis = await self._run(CommandPrompt(name="speckit.analyze"))
        critical = critical_findings(analysis)
        if critical:
            warnings.append(
                f"/speckit.analyze: {len(critical)} krytycznych niespójności, poprawiane"
            )
            await self._run(
                TextPrompt(
                    text="Fix these CRITICAL findings from the analysis by editing spec.md, "
                    "plan.md or tasks.md (keep the Spec Kit format):\n" + "\n".join(critical)
                )
            )
            graph, problems = await self._validated_tasks(feature_dir, repairs=0)
            if graph is None:
                return StageResult(ok=False, problems=problems, feature_dir=feature_dir)
        return StageResult(ok=True, feature_dir=feature_dir, graph=graph, warnings=warnings)

    async def guide(self, hint: str) -> StageResult:
        """Wskazówka użytkownika dla planisty (gdy planowanie utknęło)."""
        await self._run(TextPrompt(text=f"User guidance for the planning: {hint}"))
        return StageResult(ok=True)

    # --- pomocnicze ----------------------------------------------------------------

    def feature_dir(self) -> str | None:
        pointer = self.workspace.path / ".specify" / "feature.json"
        if pointer.exists():
            try:
                directory = str(json.loads(pointer.read_text())["feature_directory"])
            except (ValueError, KeyError, TypeError):
                directory = ""
            if directory and (self.workspace.path / directory / "spec.md").exists():
                return directory
        specs = sorted((self.workspace.path / "specs").glob("*/spec.md"))
        return str(specs[-1].parent.relative_to(self.workspace.path)) if specs else None

    async def _checked(self, path: str, check: Callable[[str], ArtifactCheck]) -> StageResult:
        """Kontrola artefaktu; przy problemach jedna poprawka w tej samej sesji."""
        target = self.workspace.path / path
        result = check(target.read_text()) if target.exists() else _missing(path)
        if not result.ok:
            await self._run(
                TextPrompt(
                    text=f"Fix {path}. Problems found by automatic checks:\n- "
                    + "\n- ".join(result.problems)
                )
            )
            result = check(target.read_text()) if target.exists() else _missing(path)
        return StageResult(ok=result.ok, problems=result.problems)

    async def _validated_tasks(
        self, feature_dir: str, *, repairs: int
    ) -> tuple[TaskGraph | None, list[str]]:
        path = Path(feature_dir) / "tasks.md"
        policy = PlanPolicy(require_tests_first=True)
        for attempt in range(repairs + 1):
            target = self.workspace.path / path
            if not target.exists():
                return None, [f"brak pliku {path}"]
            result = load_task_plan(target.read_text(), policy)
            if result.graph is not None:
                return result.graph, []
            if attempt < repairs:
                await self._run(TextPrompt(text=result.report.as_repair_prompt()))
        return None, [issue.to_prompt_line() for issue in result.report.errors]


def _missing(path: str) -> ArtifactCheck:
    return ArtifactCheck(ok=False, problems=[f"brak pliku {path}"])
