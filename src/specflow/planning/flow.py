"""Przepływ projektu: wywiad → bramki akceptacji → planowanie Spec Kit → kanban (ADR-0007).

To kolejna warstwa deterministycznego kodu (jak orkiestrator): decyduje, który etap trwa,
kiedy otworzyć bramkę i co uruchomić po akceptacji. Model pracuje tylko w dwóch miejscach:
w turach wywiadu (Interviewer) i w komendach planisty (PlanningPipeline).

    constitution ─(sloty kompletne)→ /speckit.constitution → specify
    specify ─(sloty kompletne)→ BRAMKA spec ─(akceptacja)→ /speckit.specify
        ├─ znaczniki [NEEDS CLARIFICATION] → clarify ─(odpowiedzi)→ planista uzupełnia spec
        └─ brak → plan
    plan → /speckit.plan → tasks → /speckit.tasks + walidacja + analyze → BRAMKA plan
    BRAMKA plan ─(akceptacja)→ import do kanbanu → building (orkiestrator)
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel

from specflow.domain import PlanPolicy, TaskGraph, load_task_plan
from specflow.domain.project_phase import ProjectPhase
from specflow.harness import AgentProfile, Harness, HarnessError, Session, SessionSpec
from specflow.interview import (
    Interviewer,
    InterviewState,
    render_constitution_brief,
    render_plan_summary,
    render_spec_brief,
    render_spec_summary,
)
from specflow.interview.slots import progress
from specflow.planning.checks import story_titles
from specflow.planning.pipeline import PlanningPipeline, StageResult
from specflow.storage import ProjectRow, ProjectStore
from specflow.workspace import Workspace

P = ProjectPhase
Gate = Literal["spec", "plan"]
StageFactory = Callable[[], Awaitable[StageResult]]

GATE_SPEC_PROMPT = (
    "To podsumowanie tego, co zbudujemy. Jeśli wszystko się zgadza, zatwierdź. "
    "Jeśli chcesz coś zmienić, po prostu napisz co."
)
GATE_PLAN_PROMPT = (
    "Plan jest gotowy. Zatwierdź, żeby przenieść zadania na tablicę i rozpocząć budowę, "
    "albo napisz, co zmienić w specyfikacji."
)


class FlowReply(BaseModel):
    message: str
    phase: ProjectPhase
    progress: tuple[int, int] | None = None
    gate: Gate | None = None
    gate_summary: str | None = None
    blocked: str | None = None
    """Planowanie utknęło: komunikat dla użytkownika (Awaiting input projektu)."""


class ProjectFlow:
    def __init__(
        self,
        store: ProjectStore,
        harness: Harness,
        workspace: Workspace,
        project_id: int,
        *,
        interviewer: Interviewer | None = None,
        pipeline: PlanningPipeline | None = None,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.project_id = project_id
        self.interviewer = interviewer or Interviewer(harness)
        project = store.get_project(project_id)
        self.pipeline = pipeline or PlanningPipeline(
            harness, workspace, session_id=project.planner_session_id
        )
        self._pending_graph: TaskGraph | None = None

    # --- API -----------------------------------------------------------------------

    async def start(self) -> FlowReply:
        """Otwiera wywiad (pierwsze pytanie). Ponowne wywołanie zwraca ostatnią wiadomość."""
        project = self._project()
        history = self.store.messages(self.project_id)
        if history:
            return self._reply(history[-1].text)
        return await self._interview(project, None)

    async def message(self, text: str) -> FlowReply:
        project = self._project()
        self.store.add_message(self.project_id, "user", text)
        if project.planning_message:
            return await self._retry_planning(project, text)
        if project.gate == "spec":
            self._close_gate(project)  # użytkownik chce coś zmienić - wracamy do wywiadu
        elif project.gate == "plan":
            self._close_gate(project)
            self.store.set_phase(self.project_id, P.SPECIFY)
            project.interview_state = (
                self._state(project)
                .model_copy(update={"stage": "specify", "user_wants_to_finish": False})
                .model_dump()
            )
        if P(project.phase) in (P.CONSTITUTION, P.SPECIFY, P.CLARIFY):
            return await self._interview(project, text)
        return self._reply("Trwa budowa. Postępy widać na tablicy zadań.")

    async def approve(self) -> FlowReply:
        project = self._project()
        if project.gate == "spec":
            self._close_gate(project)
            self.store.add_message(self.project_id, "user", "[zatwierdzono specyfikację]")
            return await self._after_spec_approved(project)
        if project.gate == "plan":
            self._close_gate(project)
            self.store.add_message(self.project_id, "user", "[zatwierdzono plan]")
            return self._start_building(project)
        return self._reply("Nie ma teraz nic do zatwierdzenia.")

    # --- wywiad --------------------------------------------------------------------

    async def _interview(self, project: ProjectRow, user_text: str | None) -> FlowReply:
        state = self._state(project)
        try:
            session = await self._interviewer_session(project)
            result = await self.interviewer.turn(session, state, user_text)
        except HarnessError as exc:
            self.store.commit()
            return self._reply(f"Asystent jest chwilowo niedostępny ({exc}). Spróbuj za chwilę.")
        project.interview_state = result.state.model_dump()
        self.store.add_message(self.project_id, "assistant", result.message)
        self.store.commit()
        if not result.complete:
            return self._reply(result.message, progress=result.progress)

        if result.state.stage == "constitution":
            return await self._after_constitution(project, result.state)
        if result.state.stage == "specify":
            summary = render_spec_summary(result.state)
            return self._open_gate(project, "spec", summary, GATE_SPEC_PROMPT)
        return await self._after_clarify(project, result.state)

    async def _interviewer_session(self, project: ProjectRow) -> Session:
        spec = SessionSpec(
            title="Specflow: wywiad", workdir=self.workspace.path, profile=AgentProfile.INTERVIEWER
        )
        if project.interviewer_session_id:
            return Session(id=project.interviewer_session_id, spec=spec)
        session = await self.interviewer.open_session(self.workspace.path)
        project.interviewer_session_id = session.id
        return session

    # --- etapy planowania ----------------------------------------------------------

    async def _after_constitution(self, project: ProjectRow, state: InterviewState) -> FlowReply:
        result = await self._stage(
            project,
            lambda: self.pipeline.constitution(render_constitution_brief(state, project.name)),
        )
        if not result.ok:
            return self._block(project, "Nie udało się zapisać zasad projektu", result)
        self.store.set_phase(self.project_id, P.SPECIFY)
        project.interview_state = state.model_copy(
            update={"stage": "specify", "user_wants_to_finish": False}
        ).model_dump()
        return await self._interview(project, None)

    async def _after_spec_approved(self, project: ProjectRow) -> FlowReply:
        state = self._state(project)
        result = await self._stage(
            project, lambda: self.pipeline.specify(render_spec_brief(state), len(state.stories))
        )
        if not result.ok:
            return self._block(project, "Specyfikacja nie przeszła kontroli", result)
        project.feature_dir = result.feature_dir
        if result.open_questions:
            self.store.set_phase(self.project_id, P.CLARIFY)
            project.interview_state = state.model_copy(
                update={
                    "stage": "clarify",
                    "open_questions": result.open_questions,
                    "clarifications": {},
                    "user_wants_to_finish": False,
                }
            ).model_dump()
            return await self._interview(project, None)
        self.store.set_phase(self.project_id, P.PLAN)
        return await self._plan_and_tasks(project)

    async def _after_clarify(self, project: ProjectRow, state: InterviewState) -> FlowReply:
        feature_dir = project.feature_dir or ""
        result = await self._stage(
            project, lambda: self.pipeline.clarify(feature_dir, state.clarifications)
        )
        if not result.ok:
            return self._block(project, "Nie udało się uzupełnić specyfikacji", result)
        self.store.set_phase(self.project_id, P.PLAN)
        return await self._plan_and_tasks(project)

    async def _plan_and_tasks(self, project: ProjectRow) -> FlowReply:
        feature_dir = project.feature_dir or ""
        plan = await self._stage(project, lambda: self.pipeline.plan(feature_dir))
        if not plan.ok:
            return self._block(project, "Plan techniczny nie przeszedł kontroli", plan)
        self.store.set_phase(self.project_id, P.TASKS)
        return await self._tasks(project)

    async def _tasks(self, project: ProjectRow) -> FlowReply:
        feature_dir = project.feature_dir or ""
        tasks = await self._stage(project, lambda: self.pipeline.tasks(feature_dir))
        if not tasks.ok or tasks.graph is None:
            return self._block(project, "Lista zadań nie przeszła walidacji", tasks)
        self._pending_graph = tasks.graph
        self.store.set_phase(self.project_id, P.REVIEW)
        titles = story_titles(self.workspace.read(f"{feature_dir}/spec.md"))
        summary = render_plan_summary(titles, tasks.graph)
        return self._open_gate(project, "plan", summary, GATE_PLAN_PROMPT)

    def _start_building(self, project: ProjectRow) -> FlowReply:
        graph = self._validated_graph(project)
        if graph is None:
            return self._reply("Brak zwalidowanego planu - spróbuj ponownie zatwierdzić plan.")
        self.store.import_plan(self.project_id, graph)
        self.workspace.commit("docs: specyfikacja i plan (Spec Kit)")
        self.store.set_phase(self.project_id, P.BUILDING)
        self.store.commit()
        return self._reply("Plan zatwierdzony. Zadania są na tablicy - zaczynamy budowę.")

    def _validated_graph(self, project: ProjectRow) -> TaskGraph | None:
        """Graf z ostatniej walidacji; po restarcie odtwarzany z tasks.md (bez modelu)."""
        if self._pending_graph is not None:
            return self._pending_graph
        text = self.workspace.read(f"{project.feature_dir}/tasks.md")
        return load_task_plan(text, PlanPolicy(require_tests_first=True)).graph

    async def _retry_planning(self, project: ProjectRow, hint: str) -> FlowReply:
        """Planowanie zablokowane: wiadomość użytkownika trafia do planisty jako wskazówka,
        a krok, który utknął, uruchamiamy ponownie."""
        project.planning_message = None
        await self._stage(project, lambda: self.pipeline.guide(hint))
        phase = P(project.phase)
        if phase == P.TASKS:
            return await self._tasks(project)
        if phase == P.PLAN:
            return await self._plan_and_tasks(project)
        if phase == P.CLARIFY:
            return await self._after_clarify(project, self._state(project))
        if phase == P.CONSTITUTION:
            return await self._after_constitution(project, self._state(project))
        return await self._after_spec_approved(project)

    # --- pomocnicze ----------------------------------------------------------------

    async def _stage(self, project: ProjectRow, run: StageFactory) -> StageResult:
        try:
            result = await run()
        except HarnessError as exc:
            result = StageResult(ok=False, problems=[f"agent niedostępny: {exc}"])
        project.planner_session_id = self.pipeline.session_id
        return result

    def _block(self, project: ProjectRow, title: str, result: StageResult) -> FlowReply:
        message = f"{title}: " + "; ".join(result.problems[:5])
        project.planning_message = message
        self.store.add_message(
            self.project_id,
            "system",
            message + " Napisz wskazówkę, a spróbuję jeszcze raz.",
        )
        self.store.commit()
        return self._reply(message, blocked=message)

    def _open_gate(self, project: ProjectRow, gate: Gate, summary: str, prompt: str) -> FlowReply:
        project.gate = gate
        project.gate_summary = summary
        self.store.add_message(self.project_id, "system", prompt)
        self.store.commit()
        return self._reply(prompt, gate=gate, gate_summary=summary)

    def _close_gate(self, project: ProjectRow) -> None:
        project.gate = None
        project.gate_summary = None

    def _state(self, project: ProjectRow) -> InterviewState:
        return InterviewState.model_validate(project.interview_state or {})

    def _project(self) -> ProjectRow:
        return self.store.get_project(self.project_id)

    def _reply(
        self,
        message: str,
        *,
        progress: tuple[int, int] | None = None,
        gate: Gate | None = None,
        gate_summary: str | None = None,
        blocked: str | None = None,
    ) -> FlowReply:
        project = self._project()
        if progress is None and P(project.phase) in (P.CONSTITUTION, P.SPECIFY, P.CLARIFY):
            progress = _progress(self._state(project))
        return FlowReply(
            message=message,
            phase=P(project.phase),
            progress=progress,
            gate=gate or _as_gate(project.gate),
            gate_summary=gate_summary or project.gate_summary,
            blocked=blocked or project.planning_message,
        )


def _progress(state: InterviewState) -> tuple[int, int]:
    return progress(state)


def _as_gate(value: str | None) -> Gate | None:
    if value == "spec":
        return "spec"
    if value == "plan":
        return "plan"
    return None
