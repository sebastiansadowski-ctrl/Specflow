"""Pętla orkiestratora: deterministyczny kod, który woła AI tylko przez port Harness (ADR-0001).

Jedno wywołanie `run_next()` prowadzi jedno zadanie od Ready do Done albo Awaiting input:

    Ready → In progress → (agent) → Verification → Done
                              │            └→ Rework → In progress (ta sama sesja, maks. 3)
                              └→ Awaiting input (pytanie agenta)
    po 3 nieudanych podejściach → zapis na gałęzi attempt/…, powrót do stanu bazowego,
                                   Awaiting input (wskazówka użytkownika → nowa sesja)

Awaria infrastruktury (HarnessError) nie jest porażką zadania: ponawiamy, a gdy trwa,
zadanie wraca do Ready, a projekt jest wstrzymywany (ADR-0006).
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from specflow.domain import Actor, TaskStatus
from specflow.harness import (
    AgentEvent,
    AgentProfile,
    Harness,
    HarnessError,
    RunFinished,
    Session,
    SessionSpec,
    TextPrompt,
    Usage,
)
from specflow.orchestrator.prompts import (
    PROMPT_VERSION,
    DependencyNote,
    TaskContext,
    build_answer_prompt,
    build_rework_prompt,
    build_task_prompt,
    extract_story_section,
)
from specflow.storage import ProjectStore, RunRow, TaskRow
from specflow.verification import TaskUnderTest, VerificationPolicy, Verifier
from specflow.workspace import Workspace

S = TaskStatus
EventListener = Callable[[str, AgentEvent], None]


class OrchestratorConfig(BaseModel):
    task_timeout_s: float = 1800
    harness_retries: int = 3
    retry_delays_s: list[float] = Field(default_factory=lambda: [2.0, 10.0, 30.0])
    feature_dir: str | None = None
    """Katalog funkcji Spec Kit (np. "specs/001-todo"). None = pierwszy z `specs/*/spec.md`."""


class StepOutcome(BaseModel):
    task_key: str
    outcome: Literal["done", "awaiting_input", "paused"]
    attempts: int
    message: str = ""


class _AgentRun(BaseModel):
    finished: RunFinished
    usage: Usage = Field(default_factory=Usage)


class Orchestrator:
    def __init__(
        self,
        store: ProjectStore,
        harness: Harness,
        workspace: Workspace,
        project_id: int,
        *,
        verifier: Verifier | None = None,
        policy: VerificationPolicy | None = None,
        config: OrchestratorConfig | None = None,
    ) -> None:
        self.store = store
        self.harness = harness
        self.workspace = workspace
        self.project_id = project_id
        self.policy = policy or (verifier.policy if verifier else VerificationPolicy())
        self.verifier = verifier or Verifier(harness, self.policy)
        self.config = config or OrchestratorConfig()
        self.listeners: list[EventListener] = []
        """Odbiorcy zdarzeń agenta na żywo (kanban/SSE w M5)."""

    # --- API -----------------------------------------------------------------------

    async def run_until_idle(self, max_tasks: int | None = None) -> list[StepOutcome]:
        """Wykonuje kolejne zadania Ready, aż ich zabraknie, projekt się wstrzyma
        albo osiągniemy `max_tasks`. Zadania w Awaiting input czekają na użytkownika."""
        outcomes: list[StepOutcome] = []
        while max_tasks is None or len(outcomes) < max_tasks:
            outcome = await self.run_next()
            if outcome is None:
                break
            outcomes.append(outcome)
            if outcome.outcome == "paused":
                break
        return outcomes

    def answer(self, key: str, text: str) -> TaskRow:
        """Odpowiedź na pytanie agenta albo wskazówka po wyczerpaniu prób."""
        return self.store.answer(self.project_id, key, text)

    async def run_next(self) -> StepOutcome | None:
        project = self.store.get_project(self.project_id)
        if project.paused_reason:
            return None
        task = self.store.next_ready(self.project_id)
        if task is None:
            return None
        return await self._run_task(task)

    # --- jedno zadanie -------------------------------------------------------------

    async def _run_task(self, task: TaskRow) -> StepOutcome:
        key = task.key
        base = self.workspace.head()
        spec = SessionSpec(
            title=f"{key}: {task.title}"[:120],
            workdir=self.workspace.path,
            profile=AgentProfile.TEST_WRITER if task.is_test else AgentProfile.IMPLEMENTER,
        )

        # Odpowiedź na pytanie: ta sama sesja. Inaczej: świeża sesja i pełny prompt.
        answer = task.pending_input if task.session_id else None
        try:
            if answer is not None and task.session_id:
                session = Session(id=task.session_id, spec=spec)
                question = self._last_question(key)
                prompt = build_answer_prompt(key, question, answer)
            else:
                session = await self._with_retries(lambda: self.harness.start_session(spec))
                task.session_id = session.id
                prompt = build_task_prompt(self._context(task))
        except HarnessError as exc:
            return self._pause(task, f"agent niedostępny: {exc}", started=False)
        task.pending_input = None

        self.store.set_status(self.project_id, key, S.IN_PROGRESS, Actor.ORCHESTRATOR)
        while True:
            run_row = self.store.start_run(
                self.project_id,
                key,
                session_id=session.id,
                profile=spec.profile.value,
                prompt_version=PROMPT_VERSION,
                base_sha=base,
            )
            try:
                agent = await self._run_agent(session, prompt)
            except HarnessError as exc:
                self.store.finish_run(run_row, outcome="harness_error")
                return self._pause(task, f"agent niedostępny: {exc}", started=True, base=base)
            self._record_run(run_row, agent)

            report = agent.finished.report
            if report is not None and report.status == "blocked":
                self.store.finish_run(run_row, outcome="awaiting_input")
                self.store.request_input(
                    self.project_id,
                    key,
                    Actor.ORCHESTRATOR,
                    reason="question",
                    message=report.question or report.summary,
                )
                return StepOutcome(
                    task_key=key,
                    outcome="awaiting_input",
                    attempts=task.attempts,
                    message=report.question or "",
                )

            self.store.set_status(self.project_id, key, S.VERIFICATION, Actor.ORCHESTRATOR)
            result = await self.verifier.verify(
                TaskUnderTest(key=key, title=task.title, is_test=task.is_test, files=task.files),
                agent.finished,
                self.workspace,
                base_sha=base,
                baseline_passing=set(self.store.get_project(self.project_id).passing_tests),
                baseline_known=set(self.store.get_project(self.project_id).known_tests),
                checkpoint_files=self._checkpoint_files(task),
            )
            verification = result.model_dump(mode="json", include={"ok", "checks"})

            if result.ok:
                task.commit_sha = self.workspace.commit_task(key, task.title)
                task.notes = report.notes if report else None
                task.last_feedback = None
                task.session_id = None
                if result.tests_ran:
                    self.store.save_test_baseline(
                        self.project_id, passing=result.passing, known=result.known
                    )
                self.store.finish_run(run_row, outcome="done", verification=verification)
                self.store.set_status(self.project_id, key, S.DONE, Actor.VERIFICATION)
                await self._close(session)
                return StepOutcome(task_key=key, outcome="done", attempts=task.attempts)

            task.last_feedback = result.feedback
            if result.protected_violation and base:
                self.workspace.reset_to(base)  # cofamy zmiany w testach od razu

            if task.attempts < self.policy.max_attempts:
                self.store.finish_run(run_row, outcome="rework", verification=verification)
                self.store.set_status(
                    self.project_id, key, S.REWORK, Actor.VERIFICATION, reason=result.summary()
                )
                self.store.set_status(self.project_id, key, S.IN_PROGRESS, Actor.ORCHESTRATOR)
                prompt = build_rework_prompt(
                    key,
                    result.feedback,
                    attempt=task.attempts,
                    max_attempts=self.policy.max_attempts,
                )
                continue

            branch = f"attempt/{key}-{run_row.id}"
            saved = self.workspace.save_attempt(
                branch, f"{key}: nieudana próba ({result.summary()})"
            )
            if base:
                self.workspace.reset_to(base)
            self.store.finish_run(
                run_row,
                outcome="awaiting_input",
                verification=verification,
                attempt_branch=branch if saved else None,
            )
            message = (
                f"{self.policy.max_attempts} podejścia nie przeszły weryfikacji. "
                f"Ostatnio: {result.summary()}"
                + (f" Zmiany z ostatniej próby: gałąź {branch}." if saved else "")
            )
            self.store.request_input(
                self.project_id,
                key,
                Actor.VERIFICATION,
                reason="attempts_exhausted",
                message=message,
            )
            await self._close(session)
            task.session_id = None
            return StepOutcome(
                task_key=key, outcome="awaiting_input", attempts=task.attempts, message=message
            )

    # --- agent ---------------------------------------------------------------------

    async def _run_agent(self, session: Session, prompt: str) -> _AgentRun:
        """Uruchamia agenta; przy awarii infrastruktury (HarnessError) ponawia z przerwami."""

        async def attempt() -> _AgentRun:
            finished: RunFinished | None = None
            usage = Usage()
            async for event in self.harness.run(
                session, TextPrompt(text=prompt), timeout_s=self.config.task_timeout_s
            ):
                for listener in self.listeners:
                    listener(session.id, event)
                if isinstance(event, Usage):
                    usage = Usage(
                        input_tokens=usage.input_tokens + event.input_tokens,
                        output_tokens=usage.output_tokens + event.output_tokens,
                        cost_usd=usage.cost_usd + event.cost_usd,
                    )
                elif isinstance(event, RunFinished):
                    finished = event
            if finished is None:
                raise HarnessError("Harness zakończył strumień bez RunFinished.")
            return _AgentRun(finished=finished, usage=usage)

        return await self._with_retries(attempt)

    async def _with_retries[T](self, make: Callable[[], Awaitable[T]]) -> T:
        last: HarnessError | None = None
        for n in range(self.config.harness_retries):
            try:
                return await make()
            except HarnessError as exc:
                last = exc
                if n + 1 < self.config.harness_retries:
                    delays = self.config.retry_delays_s
                    await asyncio.sleep(delays[min(n, len(delays) - 1)])
        assert last is not None
        raise last

    async def _close(self, session: Session) -> None:
        with contextlib.suppress(HarnessError):
            await self.harness.close(session)

    def _pause(
        self, task: TaskRow, reason: str, *, started: bool, base: str | None = None
    ) -> StepOutcome:
        if started:
            if base:
                self.workspace.reset_to(base)
            task.attempts = max(task.attempts - 1, 0)  # awaria nie zużywa podejścia
            self.store.set_status(
                self.project_id, task.key, S.READY, Actor.ORCHESTRATOR, reason=reason
            )
        self.store.pause(self.project_id, reason)
        return StepOutcome(
            task_key=task.key, outcome="paused", attempts=task.attempts, message=reason
        )

    # --- kontekst ------------------------------------------------------------------

    def _feature_dir(self) -> str | None:
        if self.config.feature_dir:
            return self.config.feature_dir
        specs = sorted((self.workspace.path / "specs").glob("*/spec.md"))
        return str(specs[0].parent.relative_to(self.workspace.path)) if specs else None

    def _context(self, task: TaskRow) -> TaskContext:
        feature_dir = self._feature_dir()
        acceptance = None
        if feature_dir and task.story:
            spec_path = self.workspace.path / feature_dir / "spec.md"
            if spec_path.exists():
                acceptance = extract_story_section(spec_path.read_text(), task.story)
        tasks = {t.key: t for t in self.store.board_tasks(self.project_id)}
        notes = [
            DependencyNote(key=dep, notes=tasks[dep].notes or "")
            for dep in task.depends_on
            if dep in tasks and tasks[dep].notes
        ]
        hint = task.pending_input
        return TaskContext(
            key=task.key,
            title=task.title,
            story=task.story,
            is_test=task.is_test,
            files=task.files,
            feature_dir=feature_dir,
            acceptance=acceptance,
            dependency_notes=notes,
            user_hint=hint,
            previous_failure=task.last_feedback if hint else None,
        )

    def _checkpoint_files(self, task: TaskRow) -> list[str] | None:
        """Pliki testów historyjki, jeśli `task` jest jej ostatnim zadaniem."""
        if not task.story:
            return None
        story_tasks = [t for t in self.store.board_tasks(self.project_id) if t.story == task.story]
        if not story_tasks or max(story_tasks, key=lambda t: t.order_index).key != task.key:
            return None
        files = [f for t in story_tasks if t.is_test for f in t.files]
        return files or None

    def _last_question(self, key: str) -> str | None:
        answers = [d for d in self.store.decisions(self.project_id) if d.task_key == key]
        return answers[-1].question if answers else None

    def _record_run(self, run_row: RunRow, agent: _AgentRun) -> None:
        report = agent.finished.report
        run_row.run_status = agent.finished.status
        run_row.report_status = report.status if report else None
        run_row.input_tokens = agent.usage.input_tokens
        run_row.output_tokens = agent.usage.output_tokens
        run_row.cost_usd = agent.usage.cost_usd
