"""Worker projektu: jedyny, kto zmienia stan projektu (ADR-0008).

Wzorzec: skrzynka poleceń (inbox) + jeden wykonawca na projekt. HTTP tylko dopisuje
polecenia do tabeli `commands`; worker wykonuje je po kolei, a między poleceniami
prowadzi orkiestrator (jedno zadanie na krok). Dzięki temu:
- dwie tury modelu nigdy nie działają naraz na tym samym stanie,
- polecenie przeżywa awarię (jest w bazie) i wykona się po restarcie,
- polecenie przerwane w połowie jest WZNAWIANE, a nie powtarzane na ślepo.

Pauza działa między krokami: bieżące zadanie agenta jest dokańczane. W F00 agent jest
jeden, więc odpowiedź na pytanie z innego zadania i tak czekałaby na koniec bieżącego.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from specflow.domain import InvalidTransitionError
from specflow.domain.project_phase import InvalidPhaseTransitionError, ProjectPhase
from specflow.harness import AgentEvent, Harness, RunFinished
from specflow.orchestrator import Orchestrator, OrchestratorConfig
from specflow.planning.flow import ProjectFlow
from specflow.runtime.boundary import CommittingHarness
from specflow.runtime.bus import EventBus
from specflow.storage import CommandRow, ProjectRow, ProjectStore, ProjectStoreError
from specflow.verification import VerificationPolicy
from specflow.workspace import Workspace

log = logging.getLogger(__name__)
P = ProjectPhase
MAX_COMMAND_ATTEMPTS = 3
"""Polecenie przerwane tyle razy (np. pętla awarii) kończy się błędem zamiast kolejnej próby."""
IDLE_RECHECK_S = 30.0
_MAX_EVENT_TEXT = 2000
_USER_ERRORS = (ProjectStoreError, InvalidTransitionError, InvalidPhaseTransitionError)


@dataclass
class Runtime:
    """Wspólne zależności workerów (wstrzykiwane - w testach Mock i baza tymczasowa)."""

    sessions: sessionmaker[DbSession]
    harness: Harness
    bus: EventBus
    projects_dir: Path
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)

    def store(self, session: DbSession, project_id: int) -> ProjectStore:
        return ProjectStore(session, on_commit=lambda: self.bus.notify(project_id))

    def workspace(self, project: ProjectRow) -> Workspace:
        return Workspace(Workspace.path_for(self.projects_dir, project.id, project.name))


class ProjectWorker:
    def __init__(self, project_id: int, runtime: Runtime) -> None:
        self.project_id = project_id
        self.rt = runtime
        self._stopping = False
        self._wake = asyncio.Event()

    # --- pętla ---------------------------------------------------------------------

    async def run(self) -> None:
        with self.rt.bus.subscribe(self.project_id) as signal:
            while not self._stopping:
                signal.clear()
                self._wake.clear()
                try:
                    worked = await self.step()
                except Exception:  # błąd w kodzie nie może zatrzymać całego projektu
                    log.exception("Worker projektu %s: nieoczekiwany błąd", self.project_id)
                    worked = False
                if not worked and not self._stopping:
                    await self._idle(signal)

    def stop(self) -> None:
        """Kończy pętlę po bieżącym kroku (graceful shutdown)."""
        self._stopping = True
        self._wake.set()

    async def drain(self, max_steps: int = 100) -> int:
        """Wykonuje kroki, aż nie będzie pracy (testy, skrypty). Zwraca liczbę kroków."""
        steps = 0
        while steps < max_steps and await self.step():
            steps += 1
        return steps

    async def step(self) -> bool:
        """Jeden krok: najstarsze polecenie albo jedno zadanie orkiestratora.
        Zwraca False, gdy nie było nic do zrobienia."""
        with self.rt.sessions() as session:
            store = self.rt.store(session, self.project_id)
            commands = store.pending_commands(self.project_id)
            if commands:
                await self._execute(store, commands[0])
                return True
            project = store.get_project(self.project_id)
            if not _should_build(project):
                return False
            orchestrator = self._orchestrator(store, project)
            outcome = await orchestrator.run_next()
            store.commit()
            if outcome is None:
                self._flow(store).finish_if_done()  # o fazach decyduje flow, nie worker
                return False
            return True

    async def _idle(self, signal: asyncio.Event) -> None:
        waits = [asyncio.ensure_future(signal.wait()), asyncio.ensure_future(self._wake.wait())]
        try:
            await asyncio.wait(waits, timeout=IDLE_RECHECK_S, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waits:
                waiter.cancel()

    # --- polecenia -----------------------------------------------------------------

    async def _execute(self, store: ProjectStore, command: CommandRow) -> None:
        interrupted = store.begin_command(command)
        store.commit()
        command_id = command.id
        if command.attempts > MAX_COMMAND_ATTEMPTS:
            store.finish_command(command, error="polecenie przerwane zbyt wiele razy")
            store.commit()
            return
        try:
            await self._dispatch(store, command, interrupted=interrupted)
        except _USER_ERRORS as exc:
            self._fail(store, command_id, str(exc))
            return
        except Exception as exc:
            log.exception("Polecenie %s (%s) zakończone błędem", command_id, command.kind)
            self._fail(store, command_id, f"błąd wewnętrzny: {exc}")
            return
        store.finish_command(command)
        store.commit()

    async def _dispatch(
        self, store: ProjectStore, command: CommandRow, *, interrupted: bool
    ) -> None:
        pid = self.project_id
        kind = command.kind
        if kind in ("start", "message", "approve"):
            flow = self._flow(store)
            if kind == "start":
                await flow.start()  # idempotentne: przy historii zwraca ostatnią wiadomość
            elif interrupted and self._message_logged(store, command.id):
                # Wiadomość/akceptacja zapisana, ale praca po niej przerwana: wznawiamy.
                await flow.resume_interrupted()
            elif kind == "message":
                await flow.message(command.text or "", command_id=command.id)
            else:
                await flow.approve(command_id=command.id)
        elif kind == "answer":
            store.answer(pid, command.task_key or "", command.text or "")
        elif kind == "pause":
            _require_building(store.get_project(pid))
            store.set_run_state(pid, "paused")
        elif kind == "resume":
            project = _require_building(store.get_project(pid))
            if project.paused_reason:
                store.resume(pid)
            store.set_run_state(pid, "running")

    def _fail(self, store: ProjectStore, command_id: int, error: str) -> None:
        store.session.rollback()
        command = store.session.get(CommandRow, command_id)
        if command is not None:
            store.finish_command(command, error=error)
        store.commit()

    def _message_logged(self, store: ProjectStore, command_id: int) -> bool:
        return any(m.command_id == command_id for m in store.messages(self.project_id))

    # --- składanie zależności ------------------------------------------------------

    def _harness(self, store: ProjectStore) -> CommittingHarness:
        return CommittingHarness(self.rt.harness, before_call=store.commit)

    def _flow(self, store: ProjectStore) -> ProjectFlow:
        project = store.get_project(self.project_id)
        return ProjectFlow(store, self._harness(store), self.rt.workspace(project), project.id)

    def _orchestrator(self, store: ProjectStore, project: ProjectRow) -> Orchestrator:
        orchestrator = Orchestrator(
            store,
            self._harness(store),
            self.rt.workspace(project),
            project.id,
            policy=self.rt.verification,
            config=self.rt.orchestrator.model_copy(update={"feature_dir": project.feature_dir}),
        )

        def record(task_key: str, _session_id: str, event: AgentEvent) -> None:
            store.log(
                project.id,
                f"agent_{event.kind}",
                "agent",
                task_key=task_key,
                payload=_payload(event),
            )
            store.commit()

        orchestrator.listeners.append(record)
        return orchestrator


def _should_build(project: ProjectRow) -> bool:
    return (
        P(project.phase) is P.BUILDING
        and project.run_state == "running"
        and not project.paused_reason
    )


def _require_building(project: ProjectRow) -> ProjectRow:
    if P(project.phase) is not P.BUILDING:
        raise ProjectStoreError("Pauzę i wznowienie można ustawić dopiero w trakcie budowy.")
    return project


def _payload(event: AgentEvent) -> dict[str, Any]:
    if isinstance(event, RunFinished):
        report = event.report
        return {
            "status": event.status,
            "error": event.error,
            "report_status": report.status if report else None,
            "summary": report.summary if report else None,
        }
    data = event.model_dump(mode="json")
    text = data.get("text")
    if isinstance(text, str) and len(text) > _MAX_EVENT_TEXT:
        data["text"] = text[: _MAX_EVENT_TEXT - 1] + "…"
    return data
