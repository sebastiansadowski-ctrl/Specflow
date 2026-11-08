"""Przyjmowanie poleceń z HTTP (API i widoki): sprawdzenie, zapis do skrzynki, obudzenie workera.

HTTP nie zmienia stanu projektu (ADR-0008). Sprawdzenia tutaj dają tylko szybką odpowiedź
409/404 dla poleceń, które na pewno się nie udadzą; ostatecznie decyduje worker.
"""

import asyncio
import logging
import shutil
from typing import Any

from fastapi import FastAPI, HTTPException

from specflow.domain import TaskStatus
from specflow.domain.project_phase import ProjectPhase
from specflow.runtime import Runtime, Supervisor
from specflow.storage import CHAT_COMMANDS, ProjectRow, ProjectStore, ProjectStoreError
from specflow.workspace import Workspace, WorkspaceError
from specflow.workspace.scaffold import scaffold_python

log = logging.getLogger(__name__)
BUSY = "Poczekaj chwilę, kończę poprzednią odpowiedź."


class ProjectCreationError(Exception):
    """Nie udało się przygotować workspace projektu (git, Spec Kit, szkielet)."""


async def create_project(app: FastAPI, name: str) -> int:
    """Projekt + workspace (Spec Kit przy OpenCode, szkielet Python zawsze) + start wywiadu.

    Wszystko albo nic: gdy przygotowanie workspace się nie uda, projekt i jego katalog są
    usuwane, a wywołujący dostaje ProjectCreationError z komunikatem narzędzia.
    """
    rt: Runtime = app.state.runtime
    with rt.sessions() as session:
        store = rt.store(session, 0)
        project = store.create_project(name.strip())
        store.commit()
        project_id = project.id
        path = Workspace.path_for(rt.projects_dir, project.id, project.name)
        try:
            workspace = Workspace.create(rt.projects_dir, project.id, project.name)
            if app.state.settings.should_init_spec_kit():
                await asyncio.to_thread(workspace.init_spec_kit)
            scaffold_python(workspace, project.name)
        except WorkspaceError as exc:
            log.error("Nie udało się przygotować projektu %s: %s", project_id, exc)
            store.delete_project(project_id)
            store.commit()
            shutil.rmtree(path, ignore_errors=True)
            raise ProjectCreationError(str(exc)) from exc
        store.enqueue(project_id, "start")
        store.commit()
    if app.state.start_workers:
        app.state.supervisor.ensure_worker(project_id)
    return project_id


def submit(app: FastAPI, project_id: int, kind: str, **fields: Any) -> int:
    """Zapisuje polecenie i zwraca jego id. HTTPException 404/409, gdy nie ma sensu."""
    rt: Runtime = app.state.runtime
    supervisor: Supervisor = app.state.supervisor
    with rt.sessions() as session:
        store = rt.store(session, project_id)
        try:
            project = store.get_project(project_id)
        except ProjectStoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        _check_command(store, project, kind, fields.get("task_key"))
        command = store.enqueue(project_id, kind, **fields)
        store.commit()
        command_id = command.id
    if app.state.start_workers:
        supervisor.ensure_worker(project_id)
    return command_id


def _check_command(store: ProjectStore, project: ProjectRow, kind: str, key: str | None) -> None:
    """Szybka odpowiedź 409 dla poleceń, które na pewno się nie udadzą. Ostateczną decyzję
    i tak podejmuje worker (stan mógł się zmienić, zanim polecenie zostanie wykonane)."""
    if kind in CHAT_COMMANDS and store.pending_commands(project.id, CHAT_COMMANDS):
        raise HTTPException(409, BUSY)
    if kind == "approve" and project.gate is None:
        raise HTTPException(409, "Nie ma teraz nic do zatwierdzenia.")
    if kind == "answer":
        try:
            task = store.get_task(project.id, key or "")
        except ProjectStoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        if TaskStatus(task.status) is not TaskStatus.AWAITING_INPUT:
            raise HTTPException(409, f"Zadanie {task.key} nie czeka na odpowiedź.")
    if kind in ("pause", "resume") and ProjectPhase(project.phase) is not ProjectPhase.BUILDING:
        raise HTTPException(409, "Pauzę i wznowienie można ustawić dopiero w trakcie budowy.")
