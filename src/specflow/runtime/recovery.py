"""Uzgodnienie stanu przy starcie (i po przerwaniu workera): baza + git kontra rzeczywistość.

Zasada (ADR-0008): stan żyje w bazie i w gicie; sesja modelu to tylko pamięć podręczna.
Po awarii nie próbujemy "dokończyć" przerwanej sesji agenta - zadanie zaczyna się od nowa
w czystym workspace, a przerwane podejście nie zużywa limitu prób.

Przerwane polecenia czatu (tura wywiadu, krok planisty) obsługuje worker: polecenie
oznaczone jako zaczęte, ale niezakończone, jest wznawiane (`ProjectFlow.resume_interrupted`).
"""

import asyncio
import contextlib

from specflow.domain import Actor, TaskStatus
from specflow.harness import AgentProfile, Harness, HarnessError, Session, SessionSpec
from specflow.storage import ProjectStore, RunRow, TaskRow
from specflow.workspace import Workspace

S = TaskStatus
INTERRUPTED = (S.IN_PROGRESS, S.VERIFICATION, S.REWORK)
ABORT_TIMEOUT_S = 10.0
REASON = "przerwane przez restart Specflow"


async def recover_project(
    store: ProjectStore, harness: Harness, workspace: Workspace, project_id: int
) -> list[str]:
    """Zwraca klucze zadań, które wróciły do Ready. Kolejność: najpierw sprzątanie po stronie
    agenta (bez otwartej transakcji), potem zmiany w gicie, na końcu zapis w bazie."""
    tasks = [t for t in store.board_tasks(project_id) if TaskStatus(t.status) in INTERRUPTED]
    open_runs = [r for r in store.runs(project_id) if r.finished_at is None]
    if not tasks and not open_runs:
        return []

    for task in tasks:
        if task.session_id:
            await _abort(harness, workspace, task.session_id)

    for task in tasks:
        _save_and_reset(workspace, task, _last_run(open_runs, task.key))

    for run in open_runs:
        store.finish_run(run, outcome="interrupted")
    for task in tasks:
        task.session_id = None
        task.attempts = max(task.attempts - 1, 0)  # przerwanie nie zużywa podejścia
        store.set_status(project_id, task.key, S.READY, Actor.ORCHESTRATOR, reason=REASON)
    keys = [t.key for t in tasks]
    store.log(project_id, "recovery", "system", payload={"tasks": keys, "runs": len(open_runs)})
    store.commit()
    return keys


async def _abort(harness: Harness, workspace: Workspace, session_id: str) -> None:
    """Zatrzymuje agenta, który może nadal pracować w kontenerze (i zużywać tokeny)."""
    spec = SessionSpec(title="recovery", workdir=workspace.path, profile=AgentProfile.IMPLEMENTER)
    with contextlib.suppress(HarnessError, TimeoutError):
        await asyncio.wait_for(harness.abort(Session(id=session_id, spec=spec)), ABORT_TIMEOUT_S)


def _save_and_reset(workspace: Workspace, task: TaskRow, run: RunRow | None) -> None:
    """Zmiany przerwanego podejścia trafiają na gałąź `attempt/` (do wglądu), a workspace
    wraca do stanu sprzed podejścia - jak po wyczerpaniu prób (ADR-0006)."""
    suffix = run.id if run else "x"
    workspace.save_attempt(f"attempt/{task.key}-{suffix}-interrupted", f"{task.key}: {REASON}")
    base = run.base_sha if run and run.base_sha else workspace.head()
    if base:
        workspace.reset_to(base)


def _last_run(runs: list[RunRow], key: str) -> RunRow | None:
    matching = [r for r in runs if r.task_key == key]
    return matching[-1] if matching else None
